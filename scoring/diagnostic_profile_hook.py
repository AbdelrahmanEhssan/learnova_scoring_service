"""Hook for calling initialize-track-features after assigned_track is saved.

Call notify_track_features(user_id, assigned_track) immediately after the
student_profiles.assigned_track update succeeds.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

import requests

logger = logging.getLogger("diagnostic_profile_hook")
SPECIALIZATION_TRACKS = {"DA", "DE", "DS"}


def _functions_url() -> Optional[str]:
    explicit = os.getenv("SUPABASE_FUNCTIONS_URL")
    if explicit:
        return explicit.rstrip("/")
    supabase_url = os.getenv("SUPABASE_URL")
    if supabase_url:
        return supabase_url.rstrip("/") + "/functions/v1"
    return None


def notify_track_features(user_id: str, assigned_track: str, *, previous_track: Optional[str] = None) -> bool:
    """Initialize perks/challenge scheduling for a newly assigned DA/DE/DS user.

    Returns True if the Edge Function was called and returned a successful
    response, False if skipped or failed. Failure should not fail diagnostic
    scoring because the function is idempotent and can be retried.
    """
    assigned_track = (assigned_track or "").upper()
    previous_track = (previous_track or "").upper() or None

    if assigned_track not in SPECIALIZATION_TRACKS:
        logger.info("Skipping track feature init for non-specialization track=%s user=%s", assigned_track, user_id)
        return False
    if previous_track in SPECIALIZATION_TRACKS and previous_track == assigned_track:
        logger.info("Skipping track feature init because track did not change user=%s track=%s", user_id, assigned_track)
        return False

    base = _functions_url()
    key = os.getenv("INIT_TRACK_FEATURES_API_KEY")
    if not base or not key:
        logger.error("Missing SUPABASE_FUNCTIONS_URL/SUPABASE_URL or INIT_TRACK_FEATURES_API_KEY; cannot init user=%s", user_id)
        return False

    url = f"{base}/initialize-track-features"
    payload = {"user_id": user_id}
    headers = {"Content-Type": "application/json", "x-api-key": key}

    for attempt in range(1, 4):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=12)
            if 200 <= resp.status_code < 300:
                logger.info("initialize-track-features ok user=%s track=%s response=%s", user_id, assigned_track, resp.text[:500])
                return True
            logger.warning("initialize-track-features HTTP %s attempt=%s user=%s body=%s", resp.status_code, attempt, user_id, resp.text[:500])
        except requests.RequestException as exc:
            logger.warning("initialize-track-features request failed attempt=%s user=%s error=%s", attempt, user_id, exc)
        time.sleep(0.5 * attempt)
    return False
