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


class _FailingFakeApprise(_FakeApprise):
    def notify(self, title, body):
        self.sent.append((title, body))
        return False


def test_send_returns_false_and_logs_warning_on_failure(monkeypatch, caplog):
    fake = _FailingFakeApprise()
    monkeypatch.setattr(notify_mod.apprise, "Apprise", lambda: fake)
    n = Notifier(["tgram://a/b"])
    with caplog.at_level("WARNING", logger="monitor"):
        ok = n.send("t", "b")
    assert ok is False
    assert any("t" in rec.message or "failed" in rec.message.lower() for rec in caplog.records)
