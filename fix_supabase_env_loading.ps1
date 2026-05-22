Set-Content -Path "services/supabase_client.py" -Encoding UTF8 -Value @'
import os

from dotenv import load_dotenv
from supabase import Client, create_client


load_dotenv()


SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = (
    os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    or os.getenv("SUPABASE_SERVICE_KEY")
)


if not SUPABASE_URL:
    raise RuntimeError(
        "SUPABASE_URL is not configured. Add it to your .env locally and Railway variables in production."
    )


if not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError(
        "SUPABASE_SERVICE_ROLE_KEY is not configured. Add it to your .env locally and Railway variables in production."
    )


supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY,
)
'@

Write-Host "services/supabase_client.py now loads .env safely."