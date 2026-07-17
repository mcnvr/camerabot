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
