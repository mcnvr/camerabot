from __future__ import annotations
import logging
import apprise

log = logging.getLogger("monitor")


class Notifier:
    def __init__(self, targets: list[str]):
        self._ap = apprise.Apprise()
        for t in targets:
            self._ap.add(t)

    def send(self, title: str, body: str) -> bool:
        ok = bool(self._ap.notify(title=title, body=body))
        if not ok:
            log.warning("notify send failed: %s", title)
        return ok
