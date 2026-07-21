from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

import yaml


@dataclass
class Item:
    name: str
    url: str
    sku: str
    site: str = "CANON"
    fetcher: str = "curl_cffi"  # "curl_cffi" (fast) or "browser" (zendriver, heavy)
    interval_sec: int | None = None  # per-item poll cadence; None => global default

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
    # Raw Telegram creds (when the telegram notify block is used) — powers the
    # /status listener: the token to poll/reply, and the chat_ids allowed to ask.
    telegram_token: str | None = None
    telegram_chat_ids: list[str] = field(default_factory=list)


def load_config(path: str | Path, env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

    default_fetcher = raw.get("fetcher", "curl_cffi")
    items = [
        Item(
            name=i["name"],
            url=i["url"],
            sku=str(i["sku"]),
            site=str(i.get("site", "CANON")),
            fetcher=str(i.get("fetcher", default_fetcher)),
            interval_sec=(int(i["interval_sec"]) if i.get("interval_sec") is not None else None),
        )
        for i in raw["items"]
    ]

    notify_raw = raw["notify"]
    targets: list[str] = []
    tg_token: str | None = None
    tg_chat_ids: list[str] = []
    telegram = notify_raw.get("telegram")
    if telegram:
        tg_token = telegram["bot_token"].format_map(env)
        tg_chat_ids = [c.format_map(env) for c in telegram["chat_ids"]]
        targets.extend(f"tgram://{tg_token}/{c}" for c in tg_chat_ids)
    targets.extend(t.format_map(env) for t in notify_raw.get("targets", []))

    return Config(
        interval_sec=int(raw["interval_sec"]),
        jitter_sec=int(raw.get("jitter_sec", 0)),
        fetcher=raw.get("fetcher", "curl_cffi"),
        items=items,
        notify_targets=targets,
        telegram_token=tg_token,
        telegram_chat_ids=tg_chat_ids,
    )
