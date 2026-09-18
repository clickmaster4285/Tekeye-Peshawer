from __future__ import annotations

import logging
import threading
import time

from django.conf import settings

logger = logging.getLogger(__name__)

_stop = threading.Event()
_thread: threading.Thread | None = None


def start_mobile_monitor_thread():
    global _thread
    if _thread and _thread.is_alive():
        return _thread

    def _loop():
        interval = max(15, int(getattr(settings, "CIIS_MONITOR_INTERVAL", 60)))
        while not _stop.wait(interval):
            try:
                from logs.enforcement import monitor_mobile_devices

                monitor_mobile_devices()
            except Exception:
                logger.exception("CIIS mobile device monitor failed")

    _stop.clear()
    _thread = threading.Thread(target=_loop, name="ciis-mobile-monitor", daemon=True)
    _thread.start()
    return _thread


def stop_mobile_monitor_thread():
    _stop.set()
