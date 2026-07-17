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
