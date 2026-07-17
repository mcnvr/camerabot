from monitor.state import StateStore


def test_first_time_notifies(tmp_path):
    s = StateStore(tmp_path / "state.json")
    assert s.should_notify("item1", "OUT_OF_STOCK") is True


def test_same_state_silent(tmp_path):
    s = StateStore(tmp_path / "state.json")
    s.should_notify("item1", "OUT_OF_STOCK")
    assert s.should_notify("item1", "OUT_OF_STOCK") is False


def test_transition_notifies(tmp_path):
    s = StateStore(tmp_path / "state.json")
    s.should_notify("item1", "OUT_OF_STOCK")
    assert s.should_notify("item1", "IN_STOCK") is True


def test_repeated_error_signature_silent(tmp_path):
    s = StateStore(tmp_path / "state.json")
    assert s.should_notify("item1", "ERROR:HTTP_403") is True
    assert s.should_notify("item1", "ERROR:HTTP_403") is False


def test_new_error_signature_notifies(tmp_path):
    s = StateStore(tmp_path / "state.json")
    s.should_notify("item1", "ERROR:HTTP_403")
    assert s.should_notify("item1", "ERROR:TIMEOUT") is True


def test_error_recovery_notifies(tmp_path):
    s = StateStore(tmp_path / "state.json")
    s.should_notify("item1", "ERROR:HTTP_403")
    assert s.should_notify("item1", "OUT_OF_STOCK") is True


def test_persists_across_instances(tmp_path):
    p = tmp_path / "state.json"
    StateStore(p).should_notify("item1", "OUT_OF_STOCK")
    assert StateStore(p).should_notify("item1", "OUT_OF_STOCK") is False


def test_set_baseline_then_same_silent(tmp_path):
    s = StateStore(tmp_path / "state.json")
    s.set("item1", "OUT_OF_STOCK")
    assert s.should_notify("item1", "OUT_OF_STOCK") is False
