"""Daily streak reset cron for LearNova.

Resets current_streak_days to 0 when the student has missed more than one
calendar day. Does not touch longest_streak_days.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone

from analytics._supabase_client import get_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("streak_reset")


def run() -> dict[str, object]:
    supabase = get_client()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()

    res = (
        supabase.table("user_streaks")
        .update({"current_streak_days": 0, "updated_at": datetime.now(timezone.utc).isoformat()})
        .lt("last_activity_date", cutoff)
        .gt("current_streak_days", 0)
        .execute()
    )
    reset_count = len(res.data or [])
    summary = {"ok": True, "reset_count": reset_count, "cutoff": cutoff}
    logger.info("streak_reset complete: %s", summary)
    return summary


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        logger.exception("streak_reset failed: %s", exc)
        sys.exit(1)
