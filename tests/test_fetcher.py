import pytest
import monitor.fetcher as fetcher
from monitor.fetcher import fetch, FetchError
from curl_cffi.requests.exceptions import ConnectionError as CffiConnectionError, Timeout as CffiTimeout


class _Resp:
    def __init__(self, status, text=""):
        self.status_code = status
        self.text = text


def test_returns_body_on_200(monkeypatch):
    # Fetcher is site-agnostic: any 200 body is returned verbatim. Page-validity
    # (challenge detection) is now each detector's responsibility, so a 200 with
    # no JSON-LD is NOT a fetcher-level error.
    body = "<html>anything, even without json-ld</html>"
    monkeypatch.setattr(fetcher, "_get", lambda url, timeout: _Resp(200, body))
    assert fetch("http://x") == body


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
        raise CffiConnectionError("connection reset")
    monkeypatch.setattr(fetcher, "_get", boom)
    with pytest.raises(FetchError) as ei:
        fetch("http://x")
    assert ei.value.signature == "CONN"


def test_timeout_raises_timeout_signature(monkeypatch):
    def boom(url, timeout):
        raise CffiTimeout("the request timed out")
    monkeypatch.setattr(fetcher, "_get", boom)
    with pytest.raises(FetchError) as ei:
        fetch("http://x")
    assert ei.value.signature == "TIMEOUT"
