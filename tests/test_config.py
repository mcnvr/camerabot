import pytest
from monitor.config import load_config

YAML = """
interval_sec: 45
jitter_sec: 15
fetcher: curl_cffi
items:
  - name: "Canon G7 X III (Black)"
    url: "https://example.com/p"
    sku: "3637C001"
notify:
  targets:
    - "tgram://{TELEGRAM_BOT_TOKEN}/{TELEGRAM_CHAT_ID}"
"""

def _write(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(YAML, encoding="utf-8")
    return p

def test_parses_scalars_and_items(tmp_path):
    cfg = load_config(_write(tmp_path), env={"TELEGRAM_BOT_TOKEN": "T", "TELEGRAM_CHAT_ID": "C"})
    assert cfg.interval_sec == 45
    assert cfg.jitter_sec == 15
    assert cfg.fetcher == "curl_cffi"
    assert len(cfg.items) == 1
    assert cfg.items[0].sku == "3637C001"
    assert cfg.items[0].key == "3637C001"

def test_substitutes_env_in_targets(tmp_path):
    cfg = load_config(_write(tmp_path), env={"TELEGRAM_BOT_TOKEN": "abc", "TELEGRAM_CHAT_ID": "123"})
    assert cfg.notify_targets == ["tgram://abc/123"]

def test_missing_env_raises(tmp_path):
    with pytest.raises(KeyError):
        load_config(_write(tmp_path), env={})


TELEGRAM_YAML = """
interval_sec: 45
jitter_sec: 15
fetcher: curl_cffi
items:
  - name: "Canon G7 X III (Black)"
    url: "https://example.com/p"
    sku: "3637C001"
notify:
  telegram:
    bot_token: "{TELEGRAM_BOT_TOKEN}"
    chat_ids:
      - "{TELEGRAM_CHAT_ID}"
      - "999"
  targets: []
"""

def _write_telegram(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(TELEGRAM_YAML, encoding="utf-8")
    return p

def test_telegram_block_expands_multiple_chat_ids(tmp_path):
    cfg = load_config(_write_telegram(tmp_path), env={"TELEGRAM_BOT_TOKEN": "T", "TELEGRAM_CHAT_ID": "C"})
    assert cfg.notify_targets == ["tgram://T/C", "tgram://T/999"]
