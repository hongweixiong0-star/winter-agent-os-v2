"""A bounded role-switch capability for the one existing live device.

Role switching is deliberately a transaction around the current game client. It
does not schedule tasks or persist screen state: the Scheduler chooses the role,
this controller changes the account, proves the result, and invalidates the old
role's live state before the caller starts a fresh runtime cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
from typing import Any, Callable, Mapping

import numpy as np
from PIL import Image

from .global_scheduler_state import GlobalSchedulerStateStore


AVATAR_TEMPLATE_DIR = Path("knowledge/ui/role_switch/avatar_templates")
PAID_OFFER_CLOSE_TEMPLATE = AVATAR_TEMPLATE_DIR / "paid_offer_close.png"
ROLE_AVATAR_THRESHOLD = 0.94
PAID_OFFER_CLOSE_THRESHOLD = 0.88


@dataclass(frozen=True)
class RoleSwitchResult:
    ok: bool
    role_id: str = ""
    reason: str = ""
    evidence: tuple[str, ...] = ()
    elapsed_seconds: float = 0.0


def load_role_catalog(path: Path | str) -> list[dict[str, Any]]:
    """Load only identities supported by the observed role manager artifact."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, Mapping):
        return []
    if str(payload.get("switch_status") or "").upper() != "LIVE_BIDIRECTIONAL_VERIFIED":
        return []
    rows = payload.get("roles")
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping) or not row.get("enabled", True):
            continue
        role_id = str(row.get("role_id") or "").strip()
        display_name = str(row.get("display_name") or "").strip()
        try:
            confidence = float(row.get("identity_confidence") or 0.0)
        except (TypeError, ValueError):
            continue
        if not role_id or role_id in seen or not display_name or confidence < 0.80:
            continue
        template = Path(str(row.get("avatar_template") or AVATAR_TEMPLATE_DIR / f"{role_id}.png"))
        if not template.is_absolute():
            template = Path(path).resolve().parents[2] / template
        if not template.is_file():
            continue
        normalized = dict(row)
        normalized["role_id"] = role_id
        normalized["display_name"] = display_name
        normalized["avatar_template_path"] = template
        normalized["identity_observed_at"] = str(row.get("identity_observed_at") or payload.get("observed_at") or "")
        normalized["identity_evidence"] = row.get("identity_evidence") or payload.get("evidence") or []
        out.append(normalized)
        seen.add(role_id)
    return out


def _normalized_text(value: str) -> str:
    return re.sub(r"[^0-9a-z\u3400-\u9fff]", "", str(value or "").casefold())


def _box(token: Any) -> tuple[int, int, int, int] | None:
    points = getattr(token, "box", None) or ()
    if not points:
        return None
    try:
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
    except (TypeError, ValueError, IndexError):
        return None
    if not xs or not ys:
        return None
    return int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))


class RoleSwitchController:
    """Use current-frame MAA/OCR evidence to switch and re-identify a role."""

    def __init__(
        self,
        *,
        root: Path | str,
        device: Any,
        vision: Any,
        state_store: GlobalSchedulerStateStore,
        role_catalog: list[Mapping[str, Any]],
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        max_load_seconds: float = 120.0,
        poll_seconds: float = 1.0,
    ) -> None:
        self.root = Path(root)
        self.device = device
        self.vision = vision
        self.state_store = state_store
        self.sleeper = sleeper
        self.monotonic = monotonic
        self.max_load_seconds = max(5.0, float(max_load_seconds))
        self.poll_seconds = max(0.1, float(poll_seconds))
        self.roles = {str(row.get("role_id") or ""): dict(row) for row in role_catalog
                      if row.get("role_id")}
        self.capture_root = self.root / "dataset/raw/role_switch"

    def identify_current_role(self, frame_path: Path | str) -> tuple[str, float] | None:
        """Match an observed role avatar in the supplied current screenshot."""
        try:
            image = np.asarray(Image.open(frame_path).convert("RGB"))
        except (OSError, ValueError):
            return None
        matches: list[tuple[str, float]] = []
        for role_id, entry in self.roles.items():
            template_path = Path(entry["avatar_template_path"])
            result = self._match_image(
                image, f"ROLE_AVATAR_{role_id}", template_path,
                threshold=ROLE_AVATAR_THRESHOLD,
            )
            if result is None:
                continue
            score = float(result.get("score") or 0.0)
            if result.get("hit") and (score >= ROLE_AVATAR_THRESHOLD or result.get("threshold_enforced")):
                matches.append((role_id, score))
        if len(matches) != 1:
            return None
        return matches[0]

    def switch_to(self, *, source_role_id: str, target_role_id: str,
                  reason: str) -> RoleSwitchResult:
        started = self.monotonic()
        source = self.roles.get(str(source_role_id or ""))
        target = self.roles.get(str(target_role_id or ""))
        if not source or not target:
            return RoleSwitchResult(False, reason="ROLE_ID_NOT_IN_LIVE_CATALOG")
        if source_role_id == target_role_id:
            return RoleSwitchResult(False, reason="ROLE_SWITCH_TARGET_IS_ACTIVE")
        try:
            self.state_store.begin_role_switch(
                source_role_id=source_role_id, target_role_id=target_role_id, reason=reason,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            return RoleSwitchResult(False, reason=f"ROLE_SWITCH_TRANSACTION_REFUSED:{exc}")

        evidence: list[str] = []
        try:
            current_path = self._capture("before")
            evidence.append(str(current_path))
            actual = self.identify_current_role(current_path)
            if actual is None or actual[0] != source_role_id:
                return self._abort(target_role_id, "SOURCE_ROLE_IDENTITY_NOT_CONFIRMED", evidence, started)

            # The only non-text control is the profile avatar. MAA locates the
            # role-specific image crop in this live frame and supplies the click
            # point; a stored screen coordinate is never used.
            if not self._click_template(current_path, f"ROLE_AVATAR_{source_role_id}",
                                        Path(source["avatar_template_path"]),
                                        ROLE_AVATAR_THRESHOLD):
                return self._abort(target_role_id, "PROFILE_AVATAR_NOT_LOCATED", evidence, started)

            profile_path = self._capture("profile")
            evidence.append(str(profile_path))
            identity = self._read_identity(profile_path)
            if identity is None or identity.role_id != source_role_id:
                return self._abort(target_role_id, "SOURCE_PROFILE_IDENTITY_MISMATCH", evidence, started)

            if not self._click_text(profile_path, exact=("设置",)):
                return self._abort(target_role_id, "PROFILE_SETTINGS_NOT_UNIQUE", evidence, started)
            settings_path = self._capture_until_text("settings", ("角色管理",), timeout=12.0)
            if settings_path is None:
                return self._abort(target_role_id, "ROLE_MANAGEMENT_ENTRY_NOT_OBSERVED", evidence, started)
            evidence.append(str(settings_path))
            if not self._click_text(settings_path, exact=("角色管理",)):
                return self._abort(target_role_id, "ROLE_MANAGEMENT_ENTRY_NOT_UNIQUE", evidence, started)

            manager_path = self._capture_until_role_name("role_list", target, timeout=12.0)
            if manager_path is None:
                return self._abort(target_role_id, "TARGET_ROLE_ROW_NOT_OBSERVED", evidence, started)
            evidence.append(str(manager_path))
            if not self._click_role_name(manager_path, target):
                return self._abort(target_role_id, "TARGET_ROLE_ROW_NOT_UNIQUE", evidence, started)

            confirm_path = self._capture_until_role_login_dialog(target, timeout=8.0)
            if confirm_path is None:
                return self._abort(target_role_id, "ROLE_LOGIN_CONFIRMATION_NOT_OBSERVED", evidence, started)
            evidence.append(str(confirm_path))
            if not self._click_text(confirm_path, exact=("确定", "確認")):
                return self._abort(target_role_id, "ROLE_LOGIN_CONFIRM_NOT_UNIQUE", evidence, started)

            loaded_path = self._wait_for_target_home(target, timeout=self.max_load_seconds)
            if loaded_path is None:
                return self._abort(target_role_id, "TARGET_ROLE_HOME_NOT_OBSERVED", evidence, started)
            evidence.append(str(loaded_path))

            # Reopen the target's own profile and verify the account ID printed by
            # the client. Avatar matching alone is a navigation guard, not the
            # final identity proof used to commit the transaction.
            if not self._click_template(loaded_path, f"ROLE_AVATAR_{target_role_id}",
                                        Path(target["avatar_template_path"]),
                                        ROLE_AVATAR_THRESHOLD):
                return self._abort(target_role_id, "TARGET_PROFILE_AVATAR_NOT_LOCATED", evidence, started)
            final_profile = self._capture_until_identity("target_profile", target_role_id,
                                                         timeout=8.0)
            if final_profile is None:
                return self._abort(target_role_id, "TARGET_PROFILE_IDENTITY_NOT_VERIFIED", evidence, started)
            evidence.append(str(final_profile))
            verified_identity = self._read_identity(final_profile)
            if verified_identity is None or verified_identity.role_id != target_role_id:
                return self._abort(target_role_id, "TARGET_PROFILE_ACCOUNT_ID_MISMATCH", evidence, started)

            from .state_truth import record_role

            record_role(
                self.root, verified_identity, evidence=[str(final_profile)],
                observed_at=datetime.now(timezone.utc), verification="LIVE_ROLE_SWITCH_PROFILE_READ",
            )
            self.state_store.commit_role_switch(
                confirmed_role_id=target_role_id,
                elapsed_ms=(self.monotonic() - started) * 1000.0,
            )
            return RoleSwitchResult(
                True, role_id=target_role_id, reason="ROLE_SWITCH_LIVE_PROFILE_VERIFIED",
                evidence=tuple(evidence), elapsed_seconds=self.monotonic() - started,
            )
        except Exception as exc:  # noqa: BLE001 - a failed switch must abort, never leak stale state
            return self._abort(target_role_id, f"ROLE_SWITCH_EXCEPTION:{type(exc).__name__}",
                               evidence, started)

    def _abort(self, target_role_id: str, reason: str, evidence: list[str], started: float) -> RoleSwitchResult:
        actual = ""
        try:
            path = self._capture("abort_identity")
            evidence.append(str(path))
            found = self.identify_current_role(path)
            actual = found[0] if found else ""
        except Exception:  # noqa: BLE001
            pass
        try:
            self.state_store.abort_role_switch(
                actual_role_id=actual,
                reason=reason,
                elapsed_ms=(self.monotonic() - started) * 1000.0,
            )
        except Exception:  # noqa: BLE001
            pass
        return RoleSwitchResult(False, role_id=actual, reason=reason,
                                evidence=tuple(evidence), elapsed_seconds=self.monotonic() - started)

    def _capture(self, label: str) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        destination = self.capture_root / f"{stamp}_{label}.png"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if hasattr(self.device, "capture"):
            frame = self.device.capture()
            if frame is None:
                raise RuntimeError("ROLE_SWITCH_FRAME_UNAVAILABLE")
            Image.fromarray(np.asarray(frame).astype(np.uint8)).convert("RGB").save(destination)
        else:
            self.device.screenshot(destination)
        if not destination.is_file():
            raise RuntimeError("ROLE_SWITCH_FRAME_NOT_SAVED")
        return destination

    def _match_image(self, image: np.ndarray, semantic: str, template: Path,
                     *, threshold: float) -> dict[str, Any] | None:
        if hasattr(self.device, "find"):
            outcome = self.device.find(
                image, semantic, template=semantic, threshold=threshold,
                images={semantic: template},
            )
            return {
                "hit": bool(getattr(outcome, "hit", False)),
                "score": getattr(outcome, "score", None),
                "box": getattr(outcome, "box", None),
                "center": outcome.center() if getattr(outcome, "hit", False) else None,
                "threshold_enforced": True,
            }
        # ADB fallback still derives the click point from a current-frame match.
        try:
            import cv2

            with Image.open(template) as opened:
                tpl = cv2.cvtColor(np.asarray(opened.convert("RGB")), cv2.COLOR_RGB2BGR)
            frame = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
            if tpl.shape[0] > frame.shape[0] or tpl.shape[1] > frame.shape[1]:
                return None
            scores = cv2.matchTemplate(frame, tpl, cv2.TM_CCOEFF_NORMED)
            _minimum, maximum, _minimum_at, location = cv2.minMaxLoc(scores)
            h, w = tpl.shape[:2]
            box = (int(location[0]), int(location[1]), int(w), int(h))
            return {"hit": float(maximum) >= threshold, "score": float(maximum),
                    "box": box, "center": (box[0] + w // 2, box[1] + h // 2),
                    "threshold_enforced": True}
        except Exception:  # noqa: BLE001
            return None

    def _click_template(self, frame_path: Path, semantic: str, template: Path,
                        threshold: float) -> bool:
        try:
            image = np.asarray(Image.open(frame_path).convert("RGB"))
        except (OSError, ValueError):
            return False
        result = self._match_image(image, semantic, template, threshold=threshold)
        if not result or not result.get("hit") or not result.get("center"):
            return False
        return self._click(*result["center"])

    def _click(self, x: int, y: int) -> bool:
        if hasattr(self.device, "click"):
            result = self.device.click(int(x), int(y))
            return bool(result[0]) if isinstance(result, tuple) else bool(result)
        if hasattr(self.device, "tap"):
            self.device.tap(int(x), int(y))
            return True
        return False

    def _tokens(self, frame_path: Path) -> list[Any]:
        ocr = getattr(self.vision, "ocr", None)
        if ocr is None:
            return []
        try:
            result = ocr.recognize(frame_path, None)
            return list(getattr(result, "tokens", ()) or ())
        except Exception:  # noqa: BLE001
            return []

    def _text(self, frame_path: Path) -> str:
        return " ".join(str(getattr(token, "text", "") or "")
                         for token in self._tokens(frame_path))

    def _click_text(self, frame_path: Path, *, exact: tuple[str, ...] = (),
                    contains: tuple[str, ...] = ()) -> bool:
        wanted_exact = {_normalized_text(item) for item in exact}
        wanted_contains = tuple(_normalized_text(item) for item in contains)
        candidates: list[tuple[float, tuple[int, int, int, int]]] = []
        for token in self._tokens(frame_path):
            value = _normalized_text(str(getattr(token, "text", "") or ""))
            confidence = float(getattr(token, "confidence", 0.0) or 0.0)
            box = _box(token)
            if confidence < 0.78 or box is None:
                continue
            matches = value in wanted_exact if wanted_exact else any(item and item in value for item in wanted_contains)
            if matches:
                candidates.append((confidence, box))
        if len(candidates) != 1:
            return False
        _confidence, (left, top, right, bottom) = candidates[0]
        return self._click((left + right) // 2, (top + bottom) // 2)

    def _read_identity(self, frame_path: Path) -> Any | None:
        reader = getattr(self.vision, "read_role_identity", None)
        if not callable(reader):
            return None
        try:
            return reader(frame_path)
        except Exception:  # noqa: BLE001
            return None

    def _capture_until_text(self, label: str, needles: tuple[str, ...], *, timeout: float) -> Path | None:
        deadline = self.monotonic() + timeout
        while self.monotonic() <= deadline:
            path = self._capture(label)
            text = _normalized_text(self._text(path))
            if any(_normalized_text(needle) in text for needle in needles):
                return path
            self.sleeper(self.poll_seconds)
        return None

    def _capture_until_role_name(self, label: str, target: Mapping[str, Any], *, timeout: float) -> Path | None:
        deadline = self.monotonic() + timeout
        wanted = _normalized_text(str(target.get("display_name") or ""))
        while self.monotonic() <= deadline:
            path = self._capture(label)
            text = _normalized_text(self._text(path))
            if wanted and wanted in text:
                return path
            self.sleeper(self.poll_seconds)
        return None

    def _click_role_name(self, frame_path: Path, target: Mapping[str, Any]) -> bool:
        wanted = _normalized_text(str(target.get("display_name") or ""))
        if not wanted:
            return False
        tokens = [token for token in self._tokens(frame_path)
                  if float(getattr(token, "confidence", 0.0) or 0.0) >= 0.78
                  and _box(token) is not None]
        rows: list[list[Any]] = []
        for token in sorted(tokens, key=lambda item: ((_box(item) or (0, 0, 0, 0))[1],
                                                       (_box(item) or (0, 0, 0, 0))[0])):
            box = _box(token)
            assert box is not None
            centre_y = (box[1] + box[3]) / 2.0
            row = next((candidate for candidate in rows
                        if abs(centre_y - sum((_box(item)[1] + _box(item)[3]) / 2.0
                                              for item in candidate) / len(candidate)) <= 18.0), None)
            if row is None:
                rows.append([token])
            else:
                row.append(token)
        matches: list[tuple[int, int, int, int]] = []
        for row in rows:
            row_text = _normalized_text("".join(str(getattr(token, "text", "") or "")
                                                   for token in sorted(row, key=lambda item: _box(item)[0])))
            if wanted in row_text:
                boxes = [_box(token) for token in row]
                valid = [box for box in boxes if box is not None]
                if valid:
                    matches.append((min(box[0] for box in valid), min(box[1] for box in valid),
                                    max(box[2] for box in valid), max(box[3] for box in valid)))
        if len(matches) != 1:
            return False
        left, top, right, bottom = matches[0]
        return self._click((left + right) // 2, (top + bottom) // 2)

    def _capture_until_role_login_dialog(self, target: Mapping[str, Any], *, timeout: float) -> Path | None:
        deadline = self.monotonic() + timeout
        wanted = _normalized_text(str(target.get("display_name") or ""))
        while self.monotonic() <= deadline:
            path = self._capture("login_confirm")
            text = _normalized_text(self._text(path))
            if wanted and wanted in text and "登录" in text and ("确定" in text or "確認" in text):
                return path
            self.sleeper(self.poll_seconds)
        return None

    def _capture_until_identity(self, label: str, role_id: str, *, timeout: float) -> Path | None:
        deadline = self.monotonic() + timeout
        while self.monotonic() <= deadline:
            path = self._capture(label)
            identity = self._read_identity(path)
            if identity is not None and str(getattr(identity, "role_id", "")) == role_id:
                return path
            self.sleeper(self.poll_seconds)
        return None

    def _wait_for_target_home(self, target: Mapping[str, Any], *, timeout: float) -> Path | None:
        deadline = self.monotonic() + timeout
        known_post_login = ("欢迎回来", "离线收益", "点击任意位置退出", "游历结算")
        while self.monotonic() <= deadline:
            path = self._capture("post_login")
            text = self._text(path)
            normalized = _normalized_text(text)
            if any(value in text for value in ("¥", "￥", "$")) or "超越传说礼包" in text:
                if not self._close_paid_offer(path):
                    return None
                self.sleeper(self.poll_seconds)
                continue
            if any(_normalized_text(label) in normalized for label in known_post_login):
                if self._click_text(path, exact=("确定", "確認")):
                    self.sleeper(self.poll_seconds)
                    continue
                if self._click_text(path, contains=("点击任意位置退出",)):
                    self.sleeper(self.poll_seconds)
                    continue
                # A named post-login result without an identified exit control is
                # left untouched. It can be retried after the next observation.
                return None
            avatar = self.identify_current_role(path)
            if avatar and avatar[0] == str(target.get("role_id") or ""):
                return path
            if avatar and avatar[0] != str(target.get("role_id") or ""):
                return None
            try:
                world = self.vision.observe(path)
                from .models import Page

                if world.page is Page.HOME and world.popup is None:
                    return path
            except Exception:  # noqa: BLE001
                pass
            self.sleeper(self.poll_seconds)
        return None

    def _close_paid_offer(self, frame_path: Path) -> bool:
        if not PAID_OFFER_CLOSE_TEMPLATE.is_absolute():
            template = self.root / PAID_OFFER_CLOSE_TEMPLATE
        else:
            template = PAID_OFFER_CLOSE_TEMPLATE
        if not template.is_file():
            return False
        try:
            image = np.asarray(Image.open(frame_path).convert("RGB"))
        except (OSError, ValueError):
            return False
        result = self._match_image(
            image, "ROLE_SWITCH_PAID_OFFER_CLOSE", template,
            threshold=PAID_OFFER_CLOSE_THRESHOLD,
        )
        if not result or not result.get("hit") or not result.get("center"):
            return False
        if not self._click(*result["center"]):
            return False
        after = self._capture("paid_offer_closed")
        after_text = self._text(after)
        return "超越传说礼包" not in after_text and not any(
            currency in after_text for currency in ("¥", "￥", "$"))
