"""Shared Supabase client helper for the new LearNova ML-AI repo."""
from __future__ import annotations

import logging
import os
from functools import lru_cache

from supabase import create_client, Client

logger = logging.getLogger(__name__)


class MissingSupabaseEnv(RuntimeError):
    pass


@lru_cache(maxsize=1)
def get_client() -> Client:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise MissingSupabaseEnv("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
    return create_client(url, key)
