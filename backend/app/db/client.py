"""Supabase client singleton + helpers."""
from __future__ import annotations

import logging
from typing import Any, Optional

from supabase import Client, create_client

from app.config import settings

log = logging.getLogger(__name__)

_client: Optional[Client] = None


def get_supabase() -> Optional[Client]:
    """Return a memoized Supabase client, or None if not configured."""
    global _client
    if _client is not None:
        return _client
    if not settings.has_supabase:
        log.warning("Supabase not configured — DB calls will be skipped.")
        return None
    try:
        # Normalize URL: strip trailing slash and any accidental /rest/v1 suffix
        url = settings.supabase_url.rstrip("/")
        for suffix in ("/rest/v1", "/rest"):
            if url.endswith(suffix):
                url = url[: -len(suffix)]
        _client = create_client(url, settings.supabase_service_key)
        log.info("Supabase client initialized (url=%s).", url)
        return _client
    except Exception as e:  # pragma: no cover
        log.error("Failed to init Supabase client: %s", e)
        return None


def safe_insert(table: str, row: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Insert a row; return inserted row data or None on failure."""
    client = get_supabase()
    if client is None:
        log.info("[DB MOCK] insert into %s: %s", table, row)
        return None
    try:
        resp = client.table(table).insert(row).execute()
        return resp.data[0] if resp.data else None
    except Exception as e:
        log.error("DB insert failed (%s): %s", table, e)
        return None


def safe_upsert(table: str, row: dict[str, Any], on_conflict: str = "id") -> Optional[dict[str, Any]]:
    client = get_supabase()
    if client is None:
        log.info("[DB MOCK] upsert into %s: %s", table, row)
        return None
    try:
        resp = client.table(table).upsert(row, on_conflict=on_conflict).execute()
        return resp.data[0] if resp.data else None
    except Exception as e:
        log.error("DB upsert failed (%s): %s", table, e)
        return None


def safe_update(table: str, match: dict[str, Any], values: dict[str, Any]) -> Optional[list[dict[str, Any]]]:
    client = get_supabase()
    if client is None:
        log.info("[DB MOCK] update %s where %s set %s", table, match, values)
        return None
    try:
        q = client.table(table).update(values)
        for k, v in match.items():
            q = q.eq(k, v)
        resp = q.execute()
        return resp.data or []
    except Exception as e:
        log.error("DB update failed (%s): %s", table, e)
        return None


def safe_delete(table: str, match: dict[str, Any]) -> Optional[list[dict[str, Any]]]:
    """Delete matching rows. Returns deleted row data or None on failure."""
    client = get_supabase()
    if client is None:
        return None
    try:
        q = client.table(table).delete()
        for k, v in match.items():
            q = q.eq(k, v)
        resp = q.execute()
        return resp.data or []
    except Exception as e:
        log.error("DB delete failed (%s): %s", table, e)
        return None


def safe_select(
    table: str,
    *,
    columns: str = "*",
    match: dict[str, Any] | None = None,
    order: tuple[str, bool] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Select rows. order=(column, desc). Returns [] on failure."""
    client = get_supabase()
    if client is None:
        log.info("[DB MOCK] select %s from %s where %s", columns, table, match)
        return []
    try:
        q = client.table(table).select(columns)
        if match:
            for k, v in match.items():
                q = q.eq(k, v)
        if order is not None:
            col, desc = order
            q = q.order(col, desc=desc)
        if limit is not None:
            q = q.limit(limit)
        resp = q.execute()
        return resp.data or []
    except Exception as e:
        err_str = str(e)
        # PGRST205 = table not found — treat as a config warning, not a runtime error
        if "PGRST205" in err_str or "Could not find the table" in err_str:
            log.warning("DB select: table '%s' not found in schema — skipping. %s", table, e)
        else:
            log.error("DB select failed (%s): %s", table, e)
        return []
