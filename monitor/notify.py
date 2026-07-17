from __future__ import annotations
import apprise


class Notifier:
    def __init__(self, targets: list[str]):
        self._ap = apprise.Apprise()
        for t in targets:
            self._ap.add(t)

    def send(self, title: str, body: str) -> bool:
        return bool(self._ap.notify(title=title, body=body))
