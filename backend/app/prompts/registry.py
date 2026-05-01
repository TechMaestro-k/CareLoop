from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from app.db.client import get_supabase, safe_upsert

log = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"

_yaml_cache: dict[str, dict[str, Any]] = {}
_resolved_cache: dict[str, dict[str, Any]] = {}


def clear_prompt_cache() -> dict[str, int]:
    yaml_n = len(_yaml_cache)
    resolved_n = len(_resolved_cache)
    _yaml_cache.clear()
    _resolved_cache.clear()
    log.info("Prompt cache cleared: yaml=%s resolved=%s", yaml_n, resolved_n)
    return {"yaml_cleared": yaml_n, "resolved_cleared": resolved_n}


def _load_yaml(key: str) -> dict[str, Any]:
    if key in _yaml_cache:
        return _yaml_cache[key]
    path = TEMPLATES_DIR / f"{key}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    _yaml_cache[key] = data
    return data


def _load_db_override(key: str) -> str | None:
    client = get_supabase()
    if client is None:
        return None
    try:
        resp = client.table("prompts").select("template").eq("key", key).execute()
        if resp.data:
            return resp.data[0].get("template")
    except Exception as e:
        log.warning("Prompt DB override lookup failed for %s: %s", key, e)
    return None


def get_prompt(key: str) -> dict[str, Any]:
    if key in _resolved_cache:
        return dict(_resolved_cache[key])
    base = dict(_load_yaml(key))
    override = _load_db_override(key)
    if override:
        base["user"] = override
        base["_overridden"] = True
    _resolved_cache[key] = base
    return dict(base)


def list_prompts() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(TEMPLATES_DIR.glob("*.yaml")):
        key = path.stem
        try:
            data = get_prompt(key)
        except Exception as e:
            log.error("Failed to load prompt %s: %s", key, e)
            continue
        out.append(
            {
                "key": key,
                "model": data.get("model"),
                "temperature": data.get("temperature"),
                "system": data.get("system", ""),
                "user": data.get("user", ""),
                "description": data.get("description", ""),
                "overridden": data.get("_overridden", False),
            }
        )
    return out


def save_prompt_override(key: str, template: str, edited_by: str = "ui") -> bool:
    row = {"key": key, "template": template, "edited_by": edited_by}
    res = safe_upsert("prompts", row, on_conflict="key")
    _resolved_cache.pop(key, None)
    return res is not None


def render(template: str, **vars: Any) -> str:

    class _D(dict):
        def __missing__(self, key):
            return "{" + key + "}"

    try:
        return template.format_map(_D(**vars))
    except Exception as e:
        log.error("Prompt render failed: %s", e)
        return template
