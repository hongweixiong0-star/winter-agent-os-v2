from __future__ import annotations

import re
import subprocess
from io import BytesIO
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError


NO_WINDOW_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


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
        result = subprocess.run(
            [str(self.adb_path), "-s", self.serial, *args],
            capture_output=True,
            timeout=timeout,
            check=False,
            creationflags=NO_WINDOW_FLAGS,
        )
        if result.returncode != 0:
            error = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(error or f"ADB_FAILED:{result.returncode}")
        return result.stdout if binary else result.stdout.decode("utf-8", errors="replace")

    def resolve_connection(self) -> str:
        """Prefer the configured serial; adopt only a unique online device.

        Emulator ADB ports drift between MuMu versions and multi-instance
        layouts.  A MuMu instance only shows up in `adb devices` after an
        explicit `adb connect`, so when nothing is online we probe the known
        emulator ports before giving up.  Without this, a wrong configured
        port makes every AUTO worker die with DEVICE_NOT_CONNECTED and the
        watchdog restarts it forever.
        """
        online = self._online_devices()
        if self.serial in online:
            return self.serial
        if online:
            if len(online) != 1:
                raise RuntimeError("DEVICE_AMBIGUOUS")
            self.serial = online[0]
            return self.serial
        for candidate in self._probe_candidates():
            subprocess.run([str(self.adb_path), "connect", candidate], capture_output=True,
                           timeout=10, check=False, creationflags=NO_WINDOW_FLAGS)
            online = self._online_devices()
            if self.serial in online:
                return self.serial
            if len(online) == 1:
                self.serial = online[0]
                return self.serial
            if len(online) > 1:
                raise RuntimeError("DEVICE_AMBIGUOUS")
        raise RuntimeError("DEVICE_NOT_CONNECTED")

    def _online_devices(self) -> list[str]:
        result = subprocess.run([str(self.adb_path), "devices"], capture_output=True,
                                timeout=20, check=False, creationflags=NO_WINDOW_FLAGS)
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
