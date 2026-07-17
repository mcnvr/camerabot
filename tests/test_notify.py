import monitor.notify as notify_mod
from monitor.notify import Notifier


class _FakeApprise:
    def __init__(self):
        self.added = []
        self.sent = []

    def add(self, target):
        self.added.append(target)
        return True

    def notify(self, title, body):
        self.sent.append((title, body))
        return True


def test_adds_targets_and_sends(monkeypatch):
    fake = _FakeApprise()
    monkeypatch.setattr(notify_mod.apprise, "Apprise", lambda: fake)
    n = Notifier(["tgram://a/b", "tgram://c/d"])
    assert fake.added == ["tgram://a/b", "tgram://c/d"]
    ok = n.send("t", "b")
    assert ok is True
    assert fake.sent == [("t", "b")]
