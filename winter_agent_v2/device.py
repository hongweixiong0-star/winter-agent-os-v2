from __future__ import annotations

import re
import subprocess
import time
from io import BytesIO
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError


# One runner owns how a background process is started (see winproc).  This module used to
# define its own flag constant, which is how 'most call sites are hidden' becomes a state
# rather than a rule.
from .winproc import hidden_kwargs as _hidden_kwargs


def NO_WINDOW_FLAGS_kwargs() -> dict:
    return _hidden_kwargs()


@dataclass(frozen=True)
class DeviceStatus:
    connected: bool
    serial: str
    resolution: tuple[int, int] | None
    foreground_package: str | None


class ADBDevice:
    """Small ADB boundary. Observation is always allowed; taps require production."""

    def __init__(self, adb_path: Path, serial: str, *, production: bool = False) -> None:
        self.adb_path = adb_path
        self.serial = serial
        self.production = production

    def _run(self, *args: str, binary: bool = False, timeout: float = 20.0):
        try:
            result = subprocess.run(
                [str(self.adb_path), "-s", self.serial, *args],
                capture_output=True,
                timeout=timeout,
                check=False,
                **_hidden_kwargs(),
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("ADB_COMMAND_TIMEOUT") from exc
        if result.returncode != 0:
            error = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(error or f"ADB_FAILED:{result.returncode}")
        return result.stdout if binary else result.stdout.decode("utf-8", errors="replace")

    def resolve_connection(self, *, timeout_s: float = 20.0) -> str:
        """Resolve one online device within a single bounded time budget.

        Port probing used to give each of seven `adb connect` calls and each
        `adb devices` call an independent timeout.  The control panel then
        repeated that entire sweep up to sixty times, turning one disconnected
        emulator into a many-minute worker exit.  Every subprocess below now
        consumes the same monotonic deadline; callers can use a shorter budget
        while retrying at the worker level.
        """
        budget = max(0.05, float(timeout_s))
        deadline = time.monotonic() + budget

        def remaining(cap: float) -> float:
            left = deadline - time.monotonic()
            if left <= 0:
                return 0.0
            return min(float(cap), left)

        online = self._online_devices(timeout_s=remaining(5.0))
        if self.serial in online:
            return self.serial
        if online:
            if len(online) != 1:
                raise RuntimeError("DEVICE_AMBIGUOUS")
            self.serial = online[0]
            return self.serial
        for candidate in self._probe_candidates():
            connect_timeout = remaining(1.0)
            if connect_timeout <= 0:
                break
            try:
                subprocess.run([str(self.adb_path), "connect", candidate], capture_output=True,
                               timeout=connect_timeout, check=False, **_hidden_kwargs())
            except subprocess.TimeoutExpired:
                if remaining(0.05) <= 0:
                    break
                continue
            devices_timeout = remaining(1.0)
            if devices_timeout <= 0:
                break
            try:
                online = self._online_devices(timeout_s=devices_timeout)
            except RuntimeError as exc:
                if "ADB_COMMAND_TIMEOUT" in str(exc) and remaining(0.05) > 0:
                    continue
                raise
            if self.serial in online:
                return self.serial
            if len(online) == 1:
                self.serial = online[0]
                return self.serial
            if len(online) > 1:
                raise RuntimeError("DEVICE_AMBIGUOUS")
        raise RuntimeError("DEVICE_NOT_CONNECTED")

    def _online_devices(self, *, timeout_s: float = 20.0) -> list[str]:
        try:
            result = subprocess.run([str(self.adb_path), "devices"], capture_output=True,
                                    timeout=max(0.05, float(timeout_s)), check=False, **_hidden_kwargs())
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("ADB_COMMAND_TIMEOUT") from exc
        if result.returncode:
            raise RuntimeError("ADB_DISCOVERY_FAILED")
        return [parts[0] for line in result.stdout.decode("utf-8", errors="replace").splitlines()
                if len(parts := line.split()) == 2 and parts[1] == "device"]

    def _probe_candidates(self) -> list[str]:
        """Configured serial first, then the emulator ports seen in the wild."""
        candidates = [self.serial] if self.serial else []
        serial_host = self.serial.split(":")[0] if self.serial else "127.0.0.1"
        for port in (7555, 16384, 16416, 16448, 5555, 62001, 21503):
            candidate = f"{serial_host}:{port}"
            if candidate not in candidates:
                candidates.append(candidate)
        return candidates

    def status(self) -> DeviceStatus:
        size = self._run("shell", "wm", "size")
        match = re.search(r"Physical size:\s*(\d+)x(\d+)", size)
        resolution = (int(match.group(1)), int(match.group(2))) if match else None
        focus = self._run("shell", "dumpsys", "window", "windows")
        package_match = re.search(r"mCurrentFocus=.*?\s([A-Za-z0-9_.]+)/", focus)
        if not package_match:
            activities = self._run("shell", "dumpsys", "activity", "activities")
            package_match = re.search(
                r"(?:topResumedActivity|ResumedActivity):?=.*?\s([A-Za-z0-9_.]+)/",
                activities,
            )
        return DeviceStatus(True, self.serial, resolution, package_match.group(1) if package_match else None)

    def launch(self, package_name: str) -> None:
        # Launching the app does not interact with in-game controls.
        self._run("shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1", timeout=30.0)

    def screenshot(self, destination: Path) -> Path:
        last_error = "SCREENSHOT_NOT_PNG"
        for _ in range(3):
            raw = self._run("exec-out", "screencap", "-p", binary=True, timeout=30.0)
            if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                last_error = "SCREENSHOT_NOT_PNG"
                continue
            try:
                with Image.open(BytesIO(raw)) as image:
                    image.load()
                    if image.width < 16 or image.height < 16:
                        raise ValueError("invalid screenshot dimensions")
            except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
                last_error = "SCREENSHOT_DAMAGED"
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(".tmp.png")
            temporary.write_bytes(raw)
            temporary.replace(destination)
            return destination
        raise RuntimeError(last_error)

    def tap(self, x: int, y: int) -> None:
        if not self.production:
            raise PermissionError("DRY_RUN_BLOCKED_DEVICE_ACTION")
        self._run("shell", "input", "tap", str(x), str(y))

    def press_back(self) -> None:
        if not self.production:
            raise PermissionError("DRY_RUN_BLOCKED_DEVICE_ACTION")
        self._run("shell", "input", "keyevent", "BACK")

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        """Drag between two points.

        Needed for the horizontally scrolling resource-target strip: the four
        gatherable tabs are not all on screen at the default scroll offset, so
        selecting WOOD/COAL/IRON requires moving the strip before tapping. It is
        an ordinary in-game navigation gesture, not a purchase surface.
        """
        if not self.production:
            raise PermissionError("DRY_RUN_BLOCKED_DEVICE_ACTION")
        self._run(
            "shell", "input", "swipe",
            str(x1), str(y1), str(x2), str(y2), str(max(50, int(duration_ms))),
            timeout=30.0,
        )
