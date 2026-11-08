"""Load YAML settings and unwrap rule values that carry source notes."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = ROOT / "config" / "settings.yaml"


def unwrap_annotated(node):
    """Replace {value, source_note, ...} leaves with the bare value."""
    if isinstance(node, dict) and "value" in node and "source_note" in node:
        return node["value"]
    if isinstance(node, dict):
        return {key: unwrap_annotated(value) for key, value in node.items()}
    if isinstance(node, list):
        return [unwrap_annotated(item) for item in node]
    return node


def load_rule_file(path: Path) -> dict:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    skipped = {"version", "notes"}
    values = unwrap_annotated({key: value for key, value in raw.items() if key not in skipped})
    return {
        "version": str(raw["version"]),
        "notes": str(raw.get("notes", "")),
        "values": values,
        "raw": raw,
    }


def _resolve_sqlite(url: str) -> str:
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return url
    raw_path = url[len(prefix) :]
    if raw_path == ":memory:" or raw_path.startswith("file:"):
        return url
    path = Path(raw_path)
    if not path.is_absolute():
        path = ROOT / path
    return prefix + path.resolve().as_posix()


@dataclass(frozen=True)
class GeneratorSettings:
    seed: int
    error_rate: float
    hard_negative_rate: float
    counts: dict[str, int]


@dataclass(frozen=True)
class Layer4Settings:
    z_threshold: float
    iqr_k: float
    contamination: float
    min_peer_group: int
    random_state: int


@dataclass(frozen=True)
class RiskSettings:
    weights: dict[str, float]
    low_below: float
    high_above: float


@dataclass(frozen=True)
class Settings:
    database_url: str
    enabled_families: list[str]
    logging_level: str
    generator: GeneratorSettings
    layer4: Layer4Settings
    risk: RiskSettings


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env")
    raw = yaml.safe_load(SETTINGS_PATH.read_text(encoding="utf-8"))
    database_url = os.getenv("DATABASE_URL") or raw["database_url"]
    generator = raw["generator"]
    layer4 = raw["layer4"]
    risk = raw["risk"]
    return Settings(
        database_url=_resolve_sqlite(database_url),
        enabled_families=list(raw["enabled_families"]),
        logging_level=str(raw.get("logging_level", "INFO")),
        generator=GeneratorSettings(
            seed=int(generator["seed"]),
            error_rate=float(generator["error_rate"]),
            hard_negative_rate=float(generator["hard_negative_rate"]),
            counts={str(name): int(count) for name, count in generator["counts"].items()},
        ),
        layer4=Layer4Settings(
            z_threshold=float(layer4["z_threshold"]),
            iqr_k=float(layer4["iqr_k"]),
            contamination=float(layer4["contamination"]),
            min_peer_group=int(layer4["min_peer_group"]),
            random_state=int(layer4["random_state"]),
        ),
        risk=RiskSettings(
            weights={str(name): float(value) for name, value in risk["weights"].items()},
            low_below=float(risk["low_below"]),
            high_above=float(risk["high_above"]),
        ),
    )
