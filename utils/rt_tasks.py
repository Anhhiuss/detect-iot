"""
Realtime-style helpers: latest-frame slot + capture thread + stale watchdog.

Soft RT on Linux/Pi: capture decoupled from inference; watchdog forces laser OFF if no fresh frames.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any


class LatestFrameBuffer:
    """Thread-safe single slot: always the most recent frame (copy on write)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fid = 0
        self._frame: Any = None

    def update(self, frame: Any) -> int:
        with self._lock:
            self._fid += 1
            self._frame = frame.copy()
            return self._fid

    def get(self) -> tuple[int, Any] | None:
        with self._lock:
            if self._frame is None:
                return None
            return self._fid, self._frame.copy()


def capture_loop_worker(
    cap: Any,
    buf: LatestFrameBuffer,
    stop: threading.Event,
    on_fresh_frame: Callable[[], None] | None = None,
) -> None:
    """Daemon thread target: read until stop; push copies into buf."""
    while not stop.is_set():
        ret, frame = cap.read()
        if not ret or frame is None:
            time.sleep(0.01)
            continue
        buf.update(frame)
        if on_fresh_frame is not None:
            on_fresh_frame()


class StaleFrameWatchdog:
    """
    If no heartbeat for stale_sec, call on_stale() once per episode (until frames resume).
    """

    def __init__(
        self,
        stale_sec: float,
        on_stale: Callable[[], None],
        stop: threading.Event,
        poll_interval: float = 0.2,
    ) -> None:
        self.stale_sec = stale_sec
        self.on_stale = on_stale
        self.stop = stop
        self.poll_interval = poll_interval
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def heartbeat(self) -> None:
        with self._lock:
            self._last = time.monotonic()

    def run(self) -> None:
        latched = False
        while not self.stop.wait(timeout=self.poll_interval):
            with self._lock:
                last = self._last
            age = time.monotonic() - last
            if age > self.stale_sec:
                if not latched:
                    self.on_stale()
                    latched = True
            else:
                latched = False
