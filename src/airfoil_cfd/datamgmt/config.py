"""アーカイブ設定の読込（config/archive.yaml + config/archive.local.yaml のマージ）。"""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field

import yaml

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
CONFIG_DIR = os.path.join(REPO, "config")


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


@dataclass
class Tier:
    name: str
    include: list[str]
    time_dirs: list[str]
    surfaces: str = "none"            # none | latest | all
    processor: str = "never"          # never | if_not_reconstructed | always
    les_snapshots: int = 0
    include_figures: bool = False
    description: str = ""


@dataclass
class Config:
    raw: dict
    repo: str = REPO
    tiers: dict[str, Tier] = field(default_factory=dict)

    @property
    def mount(self) -> str | None:
        m = (self.raw.get("destination") or {}).get("mount")
        return os.path.expanduser(m) if m else None

    @property
    def volume_uuid(self) -> str | None:
        return (self.raw.get("destination") or {}).get("volume_uuid")

    @property
    def archive_root(self) -> str | None:
        if not self.mount:
            return None
        return os.path.join(self.mount, self.raw["archive"]["root_dirname"])

    @property
    def mirrors(self) -> list[str]:
        return [os.path.expanduser(m) for m in (self.raw.get("mirrors") or [])]

    @property
    def mirror_tier(self) -> str:
        return self.raw["archive"].get("mirror_tier", "minimal")

    @property
    def free_space_margin(self) -> float:
        return float(self.raw["archive"].get("free_space_margin", 1.1))

    def path(self, key: str) -> str:
        return os.path.join(self.repo, self.raw[key])

    @property
    def global_exclude(self) -> list[str]:
        return list(self.raw.get("global_exclude") or [])

    @property
    def les_fields(self) -> dict:
        return self.raw.get("les_fields") or {"mean": ["*Mean"], "rms": ["*Prime2Mean"]}


def _resolve_tiers(tdefs: dict) -> dict[str, Tier]:
    resolved: dict[str, Tier] = {}

    def get(name: str, stack=()) -> Tier:
        if name in resolved:
            return resolved[name]
        if name in stack:
            raise ValueError(f"tiers の extends が循環しています: {name}")
        d = tdefs[name]
        parent = get(d["extends"], stack + (name,)) if d.get("extends") else None
        t = Tier(
            name=name,
            include=(parent.include if parent else []) + list(d.get("include") or []),
            time_dirs=list(d.get("time_dirs", parent.time_dirs if parent else [])),
            surfaces=d.get("surfaces", parent.surfaces if parent else "none"),
            processor=d.get("processor", parent.processor if parent else "never"),
            les_snapshots=int(d.get("les_snapshots", parent.les_snapshots if parent else 0)),
            include_figures=bool(d.get("include_figures",
                                       parent.include_figures if parent else False)),
            description=d.get("description", ""),
        )
        resolved[name] = t
        return t

    for n in tdefs:
        get(n)
    return resolved


def load(config_dir: str | None = None, local_override: dict | None = None) -> Config:
    """設定を読む。local_override はテスト用（archive.local.yaml の代わり）。"""
    cdir = config_dir or CONFIG_DIR
    with open(os.path.join(cdir, "archive.yaml")) as f:
        raw = yaml.safe_load(f) or {}
    local_path = os.path.join(cdir, "archive.local.yaml")
    if local_override is not None:
        raw = _deep_merge(raw, local_override)
    elif os.path.exists(local_path):
        with open(local_path) as f:
            raw = _deep_merge(raw, yaml.safe_load(f) or {})
    return Config(raw=raw, tiers=_resolve_tiers(raw.get("tiers") or {}))
