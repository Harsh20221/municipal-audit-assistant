"""Discover document families from families/<name>/family.py."""

from __future__ import annotations

import importlib
import pkgutil

import families
from families.base import DocumentFamily


def discover_families(enabled: list[str] | None = None) -> list[DocumentFamily]:
    """Return instances of enabled families.

    Directories whose names start with '_' (the template) are skipped.
    The core does not mention a family by name; config supplies the allow-list.
    """
    if enabled is None:
        from core.config import load_settings

        enabled = load_settings().enabled_families
    allowed = set(enabled)
    found: list[DocumentFamily] = []
    for info in pkgutil.iter_modules(families.__path__):
        if info.name.startswith("_") or not info.ispkg:
            continue
        module = importlib.import_module(f"families.{info.name}.family")
        for obj in vars(module).values():
            if not isinstance(obj, type) or not issubclass(obj, DocumentFamily):
                continue
            if obj is DocumentFamily or obj.name not in allowed:
                continue
            found.append(obj())
    found.sort(key=lambda family: family.name)
    return found
