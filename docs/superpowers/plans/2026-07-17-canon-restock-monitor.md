# Canon Restock Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Poll a Canon product page every ~45s and send an instant Telegram alert when it flips out-of-stock → in-stock, running 24/7 in Docker on a VPS.

**Architecture:** One polling loop drives four small units behind clean interfaces — `fetcher` (defeat Akamai via `curl_cffi` Chrome impersonation), `detector` (parse JSON-LD `offers.availability` for a sku), `state` (edge-triggered state machine persisted to JSON, de-spams alerts), `notify` (Apprise → Telegram). Config in `config.yaml`, secrets in `.env`.

**Tech Stack:** Python 3.11+, `curl_cffi`, `apprise`, `pyyaml`, `python-dotenv`, `pytest`, Docker + docker-compose.

## Global Constraints

- Python **3.11+** (uses `X | Y` type unions, `tomllib`-era stdlib, `StrEnum`-free but modern dataclasses).
- Secrets (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) live **only** in `.env` — never in `config.yaml`, code, or git. `.env`, `state.json`, `canon*.html` are gitignored.
- Detector matches the product by **sku** (`3637C001` for target), never by color string.
- In-stock rule: `offers.availability` **ends with `/InStock`**. Verified values: out = `https://schema.org/OutOfStock`, in = `https://schema.org/InStock`.
- Poll interval **30–60s + jitter**, never sub-15s (Akamai ban risk).
- Notifications are **edge-triggered**: notify only when effective state differs from last-notified state. Error signatures are bucketed (e.g. `HTTP_403`), so a repeating error alerts once.
- Every commit message ends with the Co-Authored-By trailer:
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  ```

---

## File Structure

```
resellbot/
├─ monitor/
│  ├─ __init__.py
│  ├─ detector.py     # JSON-LD parse → Status + detail; ParseError
│  ├─ state.py        # StateStore: edge-trigger + JSON persistence
│  ├─ fetcher.py      # curl_cffi fetch(url) → html; FetchError(signature)
│  ├─ notify.py       # Notifier (Apprise wrapper)
│  ├─ config.py       # load_config() → Config/Item; env substitution
│  ├─ messages.py     # format_message(item, state, detail) → (title, body)
│  └─ loop.py         # run_cycle + main loop; wires everything
├─ tests/
│  ├─ fixtures/       # canon_out.html, canon_in.html
│  ├─ test_detector.py
│  ├─ test_state.py
│  ├─ test_fetcher.py
│  ├─ test_config.py
│  └─ test_messages.py
├─ config.yaml
├─ requirements.txt
├─ Dockerfile
├─ docker-compose.yml
├─ .env.example
├─ .gitignore
└─ README.md
```

---

## Task 1: Detector

**Files:**
- Create: `monitor/__init__.py` (empty), `monitor/detector.py`
- Create fixtures: `tests/fixtures/canon_out.html`, `tests/fixtures/canon_in.html`
- Test: `tests/test_detector.py`

**Interfaces:**
- Produces:
  - `class Status(enum.Enum)` with members `IN_STOCK = "IN_STOCK"`, `OUT_OF_STOCK = "OUT_OF_STOCK"`.
  - `@dataclass class DetectResult: status: Status; availability_raw: str; price: str | None; name: str | None`
  - `def detect(html: str, sku: str) -> DetectResult`
  - `class ParseError(Exception)` — raised when no JSON-LD, or sku/availability not found.

- [ ] **Step 1: Copy the two verified HTML fixtures into the test tree**

```bash
mkdir -p tests/fixtures
cp canon.html tests/fixtures/canon_out.html
cp canon_instock.html tests/fixtures/canon_in.html
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_detector.py
from pathlib import Path
import pytest
from monitor.detector import detect, Status, ParseError

FIX = Path(__file__).parent / "fixtures"

def test_out_of_stock_target_sku():
    html = (FIX / "canon_out.html").read_text(encoding="utf-8", errors="replace")
    res = detect(html, "3637C001")
    assert res.status is Status.OUT_OF_STOCK
    assert res.availability_raw.endswith("/OutOfStock")
    assert res.price == "879.99"

def test_in_stock_fixture():
    # canon_in.html is a PowerShot V1 page (sku 6390C001), verified InStock
    html = (FIX / "canon_in.html").read_text(encoding="utf-8", errors="replace")
    res = detect(html, "6390C001")
    assert res.status is Status.IN_STOCK
    assert res.availability_raw.endswith("/InStock")

def test_unknown_sku_raises():
    html = (FIX / "canon_out.html").read_text(encoding="utf-8", errors="replace")
    with pytest.raises(ParseError):
        detect(html, "0000000")

def test_no_jsonld_raises():
    with pytest.raises(ParseError):
        detect("<html><body>no structured data</body></html>", "3637C001")
```

- [ ] **Step 3: Run tests, verify they fail**

Run: `python -m pytest tests/test_detector.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'monitor.detector'`

- [ ] **Step 4: Implement `monitor/detector.py`**

```python
# monitor/detector.py
from __future__ import annotations
import enum
import json
import re
from dataclasses import dataclass

_LD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.S | re.I,
)


class Status(enum.Enum):
    IN_STOCK = "IN_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"


@dataclass
class DetectResult:
    status: Status
    availability_raw: str
    price: str | None
    name: str | None


class ParseError(Exception):
    pass


def _iter_offers(node):
    """Yield (product_node, offer_node) pairs found anywhere in the JSON-LD tree."""
    if isinstance(node, dict):
        if "offers" in node:
            offers = node["offers"]
            for off in (offers if isinstance(offers, list) else [offers]):
                if isinstance(off, dict) and "availability" in off:
                    yield node, off
        for v in node.values():
            yield from _iter_offers(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_offers(v)


def detect(html: str, sku: str) -> DetectResult:
    blocks = _LD_RE.findall(html)
    if not blocks:
        raise ParseError("no application/ld+json block found")

    for block in blocks:
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        for product, offer in _iter_offers(data):
            if str(product.get("sku")) != sku:
                continue
            avail = offer.get("availability")
            if not isinstance(avail, str):
                raise ParseError(f"sku {sku} offer missing availability")
            status = Status.IN_STOCK if avail.rstrip("/").endswith("InStock") else Status.OUT_OF_STOCK
            price = offer.get("price")
            return DetectResult(
                status=status,
                availability_raw=avail,
                price=str(price) if price is not None else None,
                name=product.get("name"),
            )

    raise ParseError(f"sku {sku} not found in JSON-LD offers")
```

- [ ] **Step 5: Run tests, verify pass**

Run: `python -m pytest tests/test_detector.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add monitor/__init__.py monitor/detector.py tests/test_detector.py tests/fixtures/
git commit -m "feat: JSON-LD stock detector keyed on sku

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: State machine

**Files:**
- Create: `monitor/state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Consumes: nothing (pure logic + a JSON file).
- Produces:
  - `class StateStore:`
    - `__init__(self, path: str | Path)` — loads existing JSON if present.
    - `def get(self, key: str) -> str | None` — last-recorded effective state.
    - `def set(self, key: str, state: str) -> None` — force-set + persist (used for startup baseline).
    - `def should_notify(self, key: str, state: str) -> bool` — returns `True` iff `state` differs from stored; updates + persists either way.
  - Effective-state strings: `"IN_STOCK"`, `"OUT_OF_STOCK"`, or `"ERROR:<SIGNATURE>"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_state.py
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
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `python -m pytest tests/test_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'monitor.state'`

- [ ] **Step 3: Implement `monitor/state.py`**

```python
# monitor/state.py
from __future__ import annotations
import json
from pathlib import Path


class StateStore:
    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._data: dict[str, str] = {}
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def _save(self) -> None:
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        tmp.replace(self._path)  # atomic on POSIX

    def set(self, key: str, state: str) -> None:
        self._data[key] = state
        self._save()

    def should_notify(self, key: str, state: str) -> bool:
        changed = self._data.get(key) != state
        self._data[key] = state
        self._save()
        return changed
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tests/test_state.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add monitor/state.py tests/test_state.py
git commit -m "feat: edge-triggered state store with JSON persistence

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Fetcher (Strategy B + live spike)

**Files:**
- Create: `monitor/fetcher.py`
- Test: `tests/test_fetcher.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `def fetch(url: str, timeout: int = 15) -> str` — returns response body; raises `FetchError` on non-200 or transport error.
  - `class FetchError(Exception)` with attribute `signature: str` (e.g. `"HTTP_403"`, `"TIMEOUT"`, `"CONN"`).

- [ ] **Step 1: Write the failing tests (transport mocked — no network in unit tests)**

```python
# tests/test_fetcher.py
import pytest
import monitor.fetcher as fetcher
from monitor.fetcher import fetch, FetchError


class _Resp:
    def __init__(self, status, text=""):
        self.status_code = status
        self.text = text


def test_returns_body_on_200(monkeypatch):
    monkeypatch.setattr(fetcher, "_get", lambda url, timeout: _Resp(200, "<html>ok</html>"))
    assert fetch("http://x") == "<html>ok</html>"


def test_403_raises_http_signature(monkeypatch):
    monkeypatch.setattr(fetcher, "_get", lambda url, timeout: _Resp(403, "denied"))
    with pytest.raises(FetchError) as ei:
        fetch("http://x")
    assert ei.value.signature == "HTTP_403"


def test_other_status_raises_http_signature(monkeypatch):
    monkeypatch.setattr(fetcher, "_get", lambda url, timeout: _Resp(503))
    with pytest.raises(FetchError) as ei:
        fetch("http://x")
    assert ei.value.signature == "HTTP_503"


def test_transport_error_raises_conn(monkeypatch):
    def boom(url, timeout):
        raise RuntimeError("connection reset")
    monkeypatch.setattr(fetcher, "_get", boom)
    with pytest.raises(FetchError) as ei:
        fetch("http://x")
    assert ei.value.signature in ("CONN", "TIMEOUT")
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `python -m pytest tests/test_fetcher.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'monitor.fetcher'`

- [ ] **Step 3: Implement `monitor/fetcher.py`**

```python
# monitor/fetcher.py
from __future__ import annotations
from curl_cffi import requests as _cffi


class FetchError(Exception):
    def __init__(self, signature: str):
        self.signature = signature
        super().__init__(signature)


def _get(url: str, timeout: int):
    """Isolated transport call — monkeypatched in unit tests."""
    return _cffi.get(url, impersonate="chrome", timeout=timeout)


def fetch(url: str, timeout: int = 15) -> str:
    try:
        resp = _get(url, timeout)
    except Exception as e:  # curl_cffi transport failures
        sig = "TIMEOUT" if "timed out" in str(e).lower() or "timeout" in str(e).lower() else "CONN"
        raise FetchError(sig) from e
    if resp.status_code != 200:
        raise FetchError(f"HTTP_{resp.status_code}")
    return resp.text
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tests/test_fetcher.py -v`
Expected: 4 passed

- [ ] **Step 5: LIVE SPIKE — confirm `curl_cffi` beats Akamai (the gating decision)**

Run this one-off against the live target:

```bash
python -c "from monitor.fetcher import fetch; h=fetch('https://www.usa.canon.com/shop/p/powershot-g7-x-mark-iii?color=Black&type=New'); print('LEN', len(h)); print('HAS_LDJSON', 'application/ld+json' in h)"
```

Expected on success: `LEN` > 100000 and `HAS_LDJSON True`.

**Decision gate:**
- **200 + HAS_LDJSON True** → Strategy B works. Continue to Task 4.
- **`FetchError: HTTP_403`** → Akamai blocks `curl_cffi`. STOP and escalate to Strategy C (hybrid): add a `playwright` cookie-harvest that mints `_abck`/`bm_sz`, replay via `curl_cffi`. The `fetch(url) -> str` / `FetchError` interface stays identical; only `fetcher.py` internals change and `playwright` is added to `requirements.txt`. All downstream tasks are unaffected. (Escalation is a separate follow-up plan; do not build it speculatively.)

Record the spike outcome in the commit message.

- [ ] **Step 6: Commit**

```bash
git add monitor/fetcher.py tests/test_fetcher.py
git commit -m "feat: curl_cffi fetcher with Akamai-defeat spike

Spike result: <PASTE 200/403 outcome here>

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Config loader

**Files:**
- Create: `monitor/config.py`, `config.yaml`, `.env.example`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `@dataclass class Item: name: str; url: str; sku: str` with property `key -> str` (returns `sku`).
  - `@dataclass class Config: interval_sec: int; jitter_sec: int; fetcher: str; items: list[Item]; notify_targets: list[str]`
  - `def load_config(path: str | Path, env: Mapping[str, str] | None = None) -> Config` — parses YAML, substitutes `{VAR}` in `notify.targets` from `env` (defaults to `os.environ`). Missing env var → `KeyError`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_config.py
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
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'monitor.config'`

- [ ] **Step 3: Implement `monitor/config.py`**

```python
# monitor/config.py
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml


@dataclass
class Item:
    name: str
    url: str
    sku: str

    @property
    def key(self) -> str:
        return self.sku


@dataclass
class Config:
    interval_sec: int
    jitter_sec: int
    fetcher: str
    items: list[Item]
    notify_targets: list[str]


def load_config(path: str | Path, env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

    items = [Item(name=i["name"], url=i["url"], sku=str(i["sku"])) for i in raw["items"]]
    targets = [t.format_map(env) for t in raw["notify"]["targets"]]

    return Config(
        interval_sec=int(raw["interval_sec"]),
        jitter_sec=int(raw.get("jitter_sec", 0)),
        fetcher=raw.get("fetcher", "curl_cffi"),
        items=items,
        notify_targets=targets,
    )
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: 3 passed

- [ ] **Step 5: Create the real `config.yaml` and `.env.example`**

```yaml
# config.yaml
interval_sec: 45
jitter_sec: 15
fetcher: curl_cffi
items:
  - name: "Canon PowerShot G7 X Mark III (Black)"
    url: "https://www.usa.canon.com/shop/p/powershot-g7-x-mark-iii?color=Black&type=New"
    sku: "3637C001"
notify:
  targets:
    - "tgram://{TELEGRAM_BOT_TOKEN}/{TELEGRAM_CHAT_ID}"
```

```bash
# .env.example
TELEGRAM_BOT_TOKEN=your-bot-token-from-@BotFather
TELEGRAM_CHAT_ID=your-numeric-chat-id
```

- [ ] **Step 6: Commit**

```bash
git add monitor/config.py tests/test_config.py config.yaml .env.example
git commit -m "feat: yaml config loader with env substitution

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Message formatting

**Files:**
- Create: `monitor/messages.py`
- Test: `tests/test_messages.py`

**Interfaces:**
- Consumes: `Item` (Task 4), `DetectResult` (Task 1).
- Produces:
  - `def format_message(item: Item, state: str, detail: DetectResult | None) -> tuple[str, str]` — returns `(title, body)`. `detail` is `None` for error/startup states.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_messages.py
from monitor.config import Item
from monitor.detector import DetectResult, Status
from monitor.messages import format_message

ITEM = Item(name="Canon G7 X III", url="http://x/p", sku="3637C001")

def test_in_stock_message_has_url_and_price():
    detail = DetectResult(Status.IN_STOCK, "https://schema.org/InStock", "879.99", "Canon G7 X III")
    title, body = format_message(ITEM, "IN_STOCK", detail)
    assert "IN STOCK" in title.upper()
    assert "http://x/p" in body
    assert "879.99" in body

def test_out_of_stock_message():
    detail = DetectResult(Status.OUT_OF_STOCK, "https://schema.org/OutOfStock", "879.99", "Canon G7 X III")
    title, body = format_message(ITEM, "OUT_OF_STOCK", detail)
    assert "OUT OF STOCK" in title.upper()

def test_error_message_shows_signature():
    title, body = format_message(ITEM, "ERROR:HTTP_403", None)
    assert "ERROR" in title.upper()
    assert "HTTP_403" in body
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `python -m pytest tests/test_messages.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'monitor.messages'`

- [ ] **Step 3: Implement `monitor/messages.py`**

```python
# monitor/messages.py
from __future__ import annotations
from monitor.config import Item
from monitor.detector import DetectResult


def format_message(item: Item, state: str, detail: DetectResult | None) -> tuple[str, str]:
    if state == "IN_STOCK":
        price = detail.price if detail and detail.price else "?"
        return (
            f"🟢 IN STOCK: {item.name}",
            f"{item.name} is IN STOCK at ${price}\n{item.url}",
        )
    if state == "OUT_OF_STOCK":
        return (
            f"🔴 OUT OF STOCK: {item.name}",
            f"{item.name} went out of stock.\n{item.url}",
        )
    if state.startswith("ERROR:"):
        signature = state.split(":", 1)[1]
        return (
            f"⚠️ ERROR: {item.name}",
            f"Monitor error for {item.name}: {signature}\n{item.url}",
        )
    # startup/baseline or unknown
    return (
        f"✅ monitor: {item.name}",
        f"{item.name} — current state: {state}\n{item.url}",
    )
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tests/test_messages.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add monitor/messages.py tests/test_messages.py
git commit -m "feat: telegram message formatting per state

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Notifier

**Files:**
- Create: `monitor/notify.py`
- Test: (covered by monkeypatch unit test in same file's test) `tests/test_notify.py`

**Interfaces:**
- Consumes: `notify_targets: list[str]` (Task 4).
- Produces:
  - `class Notifier:` — `__init__(self, targets: list[str])`, `def send(self, title: str, body: str) -> bool` (returns Apprise's success bool).

- [ ] **Step 1: Write the failing test (Apprise stubbed — no real network)**

```python
# tests/test_notify.py
import monitor.notify as notify_mod
from monitor.notify import Notifier

class _FakeApprise:
    def __init__(self):
        self.added = []
        self.sent = []
    def add(self, target):
        self.added.append(target); return True
    def notify(self, title, body):
        self.sent.append((title, body)); return True

def test_adds_targets_and_sends(monkeypatch):
    fake = _FakeApprise()
    monkeypatch.setattr(notify_mod.apprise, "Apprise", lambda: fake)
    n = Notifier(["tgram://a/b", "tgram://c/d"])
    assert fake.added == ["tgram://a/b", "tgram://c/d"]
    ok = n.send("t", "b")
    assert ok is True
    assert fake.sent == [("t", "b")]
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `python -m pytest tests/test_notify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'monitor.notify'`

- [ ] **Step 3: Implement `monitor/notify.py`**

```python
# monitor/notify.py
from __future__ import annotations
import apprise


class Notifier:
    def __init__(self, targets: list[str]):
        self._ap = apprise.Apprise()
        for t in targets:
            self._ap.add(t)

    def send(self, title: str, body: str) -> bool:
        return bool(self._ap.notify(title=title, body=body))
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tests/test_notify.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add monitor/notify.py tests/test_notify.py
git commit -m "feat: apprise notifier wrapper

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Loop orchestration

**Files:**
- Create: `monitor/loop.py`
- Test: `tests/test_loop.py`

**Interfaces:**
- Consumes: `fetch`/`FetchError` (Task 3), `detect`/`ParseError`/`DetectResult` (Task 1), `StateStore` (Task 2), `Config`/`Item` (Task 4), `format_message` (Task 5), `Notifier` (Task 6).
- Produces:
  - `def run_cycle(item: Item, fetch_fn, detect_fn) -> tuple[str, DetectResult | None]` — returns `(state, detail)`. `state` is `"IN_STOCK"`/`"OUT_OF_STOCK"`/`"ERROR:<SIG>"`; `detail` is the `DetectResult` on success else `None`. Never raises.
  - `def main() -> None` — loads env + config, sends startup baseline pings, then polls forever with jitter.

- [ ] **Step 1: Write the failing tests for `run_cycle` (pure, no sleeping)**

```python
# tests/test_loop.py
from monitor.config import Item
from monitor.detector import DetectResult, Status, ParseError
from monitor.fetcher import FetchError
from monitor.loop import run_cycle

ITEM = Item(name="X", url="http://x", sku="3637C001")

def test_cycle_in_stock():
    fetch_fn = lambda url: "<html/>"
    detect_fn = lambda html, sku: DetectResult(Status.IN_STOCK, "https://schema.org/InStock", "879.99", "X")
    state, detail = run_cycle(ITEM, fetch_fn, detect_fn)
    assert state == "IN_STOCK"
    assert detail.price == "879.99"

def test_cycle_out_of_stock():
    fetch_fn = lambda url: "<html/>"
    detect_fn = lambda html, sku: DetectResult(Status.OUT_OF_STOCK, "https://schema.org/OutOfStock", "879.99", "X")
    state, detail = run_cycle(ITEM, fetch_fn, detect_fn)
    assert state == "OUT_OF_STOCK"

def test_cycle_fetch_error_maps_signature():
    def fetch_fn(url):
        raise FetchError("HTTP_403")
    detect_fn = lambda html, sku: None
    state, detail = run_cycle(ITEM, fetch_fn, detect_fn)
    assert state == "ERROR:HTTP_403"
    assert detail is None

def test_cycle_parse_error_maps_to_parse_fail():
    fetch_fn = lambda url: "<html/>"
    def detect_fn(html, sku):
        raise ParseError("no sku")
    state, detail = run_cycle(ITEM, fetch_fn, detect_fn)
    assert state == "ERROR:PARSE_FAIL"
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `python -m pytest tests/test_loop.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'monitor.loop'`

- [ ] **Step 3: Implement `monitor/loop.py`**

```python
# monitor/loop.py
from __future__ import annotations
import logging
import random
import time

from dotenv import load_dotenv

from monitor.config import Config, Item, load_config
from monitor.detector import DetectResult, ParseError, detect
from monitor.fetcher import FetchError, fetch
from monitor.messages import format_message
from monitor.notify import Notifier
from monitor.state import StateStore

log = logging.getLogger("monitor")


def run_cycle(item: Item, fetch_fn, detect_fn) -> tuple[str, DetectResult | None]:
    try:
        html = fetch_fn(item.url)
    except FetchError as e:
        return f"ERROR:{e.signature}", None
    try:
        res = detect_fn(html, item.sku)
    except ParseError:
        return "ERROR:PARSE_FAIL", None
    return res.status.value, res


def _sleep_with_jitter(cfg: Config) -> None:
    time.sleep(cfg.interval_sec + random.uniform(0, cfg.jitter_sec))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_dotenv()
    cfg = load_config("config.yaml")
    store = StateStore("state.json")
    notifier = Notifier(cfg.notify_targets)

    # Startup baseline ping — one per item, then silent until a transition.
    for item in cfg.items:
        state, detail = run_cycle(item, fetch, detect)
        store.set(item.key, state)
        title, body = format_message(item, state, detail)
        notifier.send(f"✅ monitor started — {item.name}", f"current: {state}\n{body}")
        log.info("startup %s -> %s", item.name, state)

    while True:
        for item in cfg.items:
            state, detail = run_cycle(item, fetch, detect)
            if store.should_notify(item.key, state):
                title, body = format_message(item, state, detail)
                notifier.send(title, body)
                log.info("NOTIFY %s -> %s", item.name, state)
            else:
                log.info("no change %s -> %s", item.name, state)
        _sleep_with_jitter(cfg)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tests/test_loop.py -v`
Expected: 4 passed

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -v`
Expected: all tests pass (detector 4, state 8, fetcher 4, config 3, messages 3, notify 1, loop 4).

- [ ] **Step 6: Commit**

```bash
git add monitor/loop.py tests/test_loop.py
git commit -m "feat: polling loop wiring fetch/detect/state/notify

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Dockerize + docs + end-to-end run

**Files:**
- Create: `requirements.txt`, `Dockerfile`, `docker-compose.yml`, `README.md`
- Modify: `.gitignore` (ensure `state.json`, `.env`, `canon*.html`, `__pycache__` covered — already present from spec commit; verify)

**Interfaces:** none (packaging).

- [ ] **Step 1: Write `requirements.txt`**

```
curl_cffi>=0.7
apprise>=1.8
pyyaml>=6.0
python-dotenv>=1.0
pytest>=8.0
```

- [ ] **Step 2: Write `Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY monitor/ ./monitor/
COPY config.yaml ./

# state.json persisted via a mounted volume (see docker-compose.yml)
CMD ["python", "-m", "monitor.loop"]
```

- [ ] **Step 3: Write `docker-compose.yml`**

```yaml
services:
  monitor:
    build: .
    restart: unless-stopped
    env_file: .env
    volumes:
      - monitor-state:/app/state
    # loop.py writes state.json in CWD (/app); mount the volume there via a symlink-free path:
    working_dir: /app
    command: ["python", "-m", "monitor.loop"]

volumes:
  monitor-state:
```

> Note: to persist `state.json` on the named volume, set `StateStore` path via CWD. Keep `state.json` at `/app/state/state.json` by editing `loop.py` `StateStore("state.json")` → `StateStore("state/state.json")` and add `RUN mkdir -p /app/state` to the Dockerfile. Do this in Step 4.

- [ ] **Step 4: Point state at the mounted volume**

Edit `monitor/loop.py`: change `store = StateStore("state.json")` to `store = StateStore("state/state.json")`.
Edit `Dockerfile`: add `RUN mkdir -p /app/state` after `WORKDIR /app`.

Run the suite again to confirm nothing broke:
Run: `python -m pytest -v`
Expected: all pass (loop tests don't touch that path).

- [ ] **Step 5: Write `README.md`**

```markdown
# resellbot — Canon restock monitor

Polls a Canon product page and sends a Telegram alert when it restocks.

## Setup
1. Create a Telegram bot via @BotFather → get `TELEGRAM_BOT_TOKEN`.
2. Get your numeric chat id (message the bot, then check `https://api.telegram.org/bot<TOKEN>/getUpdates`).
3. `cp .env.example .env` and fill both values.
4. Edit `config.yaml` to set the item URL + sku.

## Run (Docker)
    docker compose up -d --build
    docker compose logs -f

## Run (local)
    pip install -r requirements.txt
    python -m monitor.loop

## Test
    python -m pytest -v
```

- [ ] **Step 6: End-to-end smoke test (real Telegram, real fetch)**

With a filled `.env`:

```bash
pip install -r requirements.txt
python -m monitor.loop
```

Expected: a Telegram "✅ monitor started — Canon PowerShot G7 X Mark III (Black)" message arrives within seconds, log shows `startup ... -> OUT_OF_STOCK` (item is currently out of stock). Ctrl-C after confirming.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt Dockerfile docker-compose.yml README.md monitor/loop.py
git commit -m "feat: dockerize monitor + README + volume-backed state

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review Notes

- **Spec coverage:** detector (Task 1), fetcher B + spike/escalation gate (Task 3), state machine incl. error bucketing + startup ping (Tasks 2, 7), Telegram via Apprise (Tasks 4, 6), config (Task 4), Docker/VPS deploy (Task 8), 45s±15s jitter (Tasks 4, 7), tests against both fixtures (Task 1). All covered.
- **Escalation to hybrid C:** intentionally NOT built (YAGNI) — Task 3 spike decides; interface preserved so it's additive.
- **Type consistency:** `Status.value` strings (`"IN_STOCK"`/`"OUT_OF_STOCK"`) match state strings used in `state.py`, `messages.py`, `loop.py`. `DetectResult` fields consistent across Tasks 1/5/7. `FetchError.signature` consistent across Tasks 3/7.
```
