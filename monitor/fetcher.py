from __future__ import annotations
from curl_cffi import requests as _cffi
from curl_cffi.requests.exceptions import RequestException, Timeout


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
    except RequestException as e:  # curl_cffi typed transport failures
        sig = "TIMEOUT" if isinstance(e, Timeout) else "CONN"
        raise FetchError(sig) from e
    if resp.status_code != 200:
        raise FetchError(f"HTTP_{resp.status_code}")
    if "application/ld+json" not in resp.text:
        raise FetchError("CHALLENGE")
    return resp.text
