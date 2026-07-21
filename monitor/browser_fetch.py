from __future__ import annotations
import asyncio
import logging
import os

from monitor.fetcher import FetchError

log = logging.getLogger("monitor")

# Chrome flags tuned for a memory-constrained container. We only need the
# hydrated DOM, so image decoding is off. --no-sandbox / --disable-dev-shm-usage
# are required when running as root with a small /dev/shm (i.e. in Docker).
_CHROME_ARGS = [
    "--disable-gpu",
    "--disable-dev-shm-usage",
    "--blink-settings=imagesEnabled=false",
    "--disable-extensions",
    "--disable-background-networking",
    "--mute-audio",
]

# Seconds to let the page run its JS (bot-defense sensor + hydration + the XHR
# that populates stock) before snapshotting the DOM. Tunable via env.
_HYDRATE_SECONDS = float(os.getenv("BROWSER_HYDRATE_SECONDS", "9"))


def fetch_browser(url: str, timeout: int = 60) -> str:
    """Fetch a JS-hydrated page via a real headless Chrome (zendriver).

    For sites whose stock only appears after client-side hydration behind bot
    protection curl can't pass (Target/PerimeterX). Chrome is launched per call
    and fully stopped afterwards so peak memory is transient rather than
    resident — important on a small VPS. Any browser/transport failure is
    surfaced as FetchError("BROWSER_ERR") so the caller debounces/retries it the
    same as any other fetch error.
    """
    try:
        return asyncio.run(_afetch(url, timeout))
    except Exception as e:
        log.warning("browser fetch failed for %s: %r", url, e)
        raise FetchError("BROWSER_ERR") from e


async def _afetch(url: str, timeout: int) -> str:
    import zendriver as zd  # lazy: curl-only deploys never import this

    # sandbox=False makes zendriver add --no-sandbox, required to run Chrome as
    # root in Docker. (The param is `sandbox`, NOT `no_sandbox` — the latter is
    # silently swallowed by **kwargs and leaves the sandbox on.)
    kwargs = dict(headless=True, sandbox=False, browser_args=list(_CHROME_ARGS))
    # In slim Docker the binary is /usr/bin/chromium; point zendriver at it
    # explicitly so it doesn't rely on auto-detecting a Chrome install.
    chrome_path = os.getenv("ZENDRIVER_BROWSER_PATH") or os.getenv("CHROME_PATH")
    if chrome_path:
        kwargs["browser_executable_path"] = chrome_path

    browser = await zd.start(**kwargs)
    try:
        tab = await asyncio.wait_for(browser.get(url), timeout=timeout)
        await asyncio.sleep(_HYDRATE_SECONDS)
        return await tab.get_content()
    finally:
        try:
            await browser.stop()
        except Exception:
            pass
