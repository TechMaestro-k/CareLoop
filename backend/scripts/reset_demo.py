"""Hard-reset the CareLoop demo database.

Wipes every CareLoop table via the Supabase REST API (delete-by-id),
then re-runs the synthetic-patient seed so the demo is in a known state.

Usage:
    cd careloop/careloop/backend
    python -m scripts.reset_demo
"""
from __future__ import annotations

import logging
import sys

from app.db.client import get_supabase
from app.seed.synthetic_patients import run_seed

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("reset_demo")

# Order matters: child tables first so foreign keys never block a delete,
# even though most CareLoop FKs are ON DELETE CASCADE.
WIPE_ORDER = [
    "reasoning_traces",
    "slot_proposals",
    "interactions",
    "escalations",
    "care_plans",
    "knowledge_graphs",
    "sdoh_profiles",
    "clinical_data",
    "medications_inventory",
    "patients",
    "doctors",
    "prompts",
]


def _delete_all(table: str) -> int:
    client = get_supabase()
    if client is None:
        log.error("Supabase not configured; cannot reset.")
        sys.exit(1)
    try:
        key_col = "key" if table == "prompts" else "id"
        before = client.table(table).select("*", count="exact").limit(1).execute()
        n_before = before.count or 0
        if n_before == 0:
            log.info("%-22s already empty", table)
            return 0
        client.table(table).delete().neq(key_col, "00000000-0000-0000-0000-000000000000").execute()
        after = client.table(table).select("*", count="exact").limit(1).execute()
        n_after = after.count or 0
        log.info("%-22s wiped %d → %d rows", table, n_before, n_after)
        return n_before - n_after
    except Exception as e:
        log.error("wipe failed (%s): %s", table, e)
        return 0


def main() -> None:
    log.info("=== CareLoop demo reset ===")
    total = 0
    for t in WIPE_ORDER:
        total += _delete_all(t)
    log.info("Total rows wiped: %d", total)
    log.info("--- Reseeding synthetic patients ---")
    result = run_seed()
    log.info("Seed result: %s", result)
    log.info("Done.")


if __name__ == "__main__":
    main()
