"""Daily cron to expire skipped weekly challenges and schedule the next one."""
from __future__ import annotations

import logging
import sys

from analytics._supabase_client import get_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("expire_challenges")


def run() -> dict[str, object]:
    supabase = get_client()
    result = supabase.rpc("expire_and_reschedule_stale_challenges", {}).execute()
    data = result.data or {}
    if data.get("ok") is False:
        raise RuntimeError(f"expire_and_reschedule_stale_challenges returned failure: {data}")
    expired_count = int(data.get("expired_count") or 0)
    rescheduled_count = int(data.get("rescheduled_count") or 0)
    logger.info(
        "expire_challenges complete: expired_count=%s rescheduled_count=%s",
        expired_count,
        rescheduled_count,
    )
    if expired_count > rescheduled_count:
        logger.warning(
            "Expired %s challenge(s) without scheduling next week. This is OK if content has no next challenge yet.",
            expired_count - rescheduled_count,
        )
    return {"ok": True, "expired_count": expired_count, "rescheduled_count": rescheduled_count}


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        logger.exception("expire_challenges failed: %s", exc)
        sys.exit(1)
