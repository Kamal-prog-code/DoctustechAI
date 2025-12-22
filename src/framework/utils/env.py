from __future__ import annotations


def parse_bool_env(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}
