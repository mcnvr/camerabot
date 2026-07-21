import pytest
import monitor.browser_fetch as bf
from monitor.fetcher import FetchError


def test_fetch_browser_returns_html(monkeypatch):
    async def fake(url, timeout):
        return "<html>hydrated</html>"
    monkeypatch.setattr(bf, "_afetch", fake)
    assert bf.fetch_browser("http://x") == "<html>hydrated</html>"


def test_fetch_browser_wraps_errors_as_fetcherror(monkeypatch):
    async def boom(url, timeout):
        raise RuntimeError("chrome crashed")
    monkeypatch.setattr(bf, "_afetch", boom)
    with pytest.raises(FetchError) as ei:
        bf.fetch_browser("http://x")
    assert ei.value.signature == "BROWSER_ERR"
