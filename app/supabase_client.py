"""A small Supabase client over PostgREST, using only the standard library.

Everything the agent does in the cloud is either a table read (`select`) or a
stored procedure call (`rpc`). That is two HTTP shapes, so there is no reason to
pull in a driver or an SDK; `urllib` is enough and keeps `requirements.txt`
honest.

The service-role key is read from the environment and never logged. It bypasses
Row Level Security, so it belongs on a server and in `.env`, never in a browser
and never in git.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

# Transient things worth trying again: PostgREST restarts, Supabase pausing a
# free-tier project, a dropped connection. A 4xx is our bug, so it is not here.
RETRY_STATUSES = {502, 503, 504}
MAX_ATTEMPTS = 3


class SupabaseError(RuntimeError):
    """Any failure talking to Supabase, with the server's explanation attached."""


class SupabaseClient:
    def __init__(self, url: str | None = None, key: str | None = None, timeout: float = 30.0):
        self.url = (url or os.getenv("SUPABASE_URL", "")).strip().rstrip("/")
        self.key = (key or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")).strip()
        self.timeout = timeout
        if not self.url or not self.key:
            raise SupabaseError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set. "
                "Copy .env.example to .env and fill it in."
            )
        if not self.url.startswith("https://"):
            raise SupabaseError(f"SUPABASE_URL should start with https:// (got {self.url!r})")

    # ------------------------------------------------------------------ HTTP

    def _headers(self, extra: dict | None = None) -> dict:
        headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if extra:
            headers.update(extra)
        return headers

    def _send(self, method: str, path: str, *, query: str = "", body=None, headers=None):
        """One request, with a couple of retries on transient server errors."""
        url = f"{self.url}/rest/v1/{path.lstrip('/')}"
        if query:
            url += "?" + query
        data = None if body is None else json.dumps(body, default=str).encode("utf-8")
        request = urllib.request.Request(
            url, data=data, headers=self._headers(headers), method=method)

        last_error: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read().decode("utf-8")
                    return json.loads(raw) if raw.strip() else None
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                if exc.code in RETRY_STATUSES and attempt < MAX_ATTEMPTS:
                    last_error = exc
                    time.sleep(0.5 * attempt)
                    continue
                # 401/403 here nearly always means the wrong key, so say so.
                hint = ""
                if exc.code in (401, 403):
                    hint = (" Check SUPABASE_SERVICE_ROLE_KEY: every table has RLS enabled,"
                            " so the anon key cannot read anything.")
                if exc.code == 404:
                    hint = " Have you run schema/supabase.sql in the SQL Editor yet?"
                raise SupabaseError(f"Supabase HTTP {exc.code} on {method} {path}: {detail}{hint}") from exc
            except urllib.error.URLError as exc:
                if attempt < MAX_ATTEMPTS:
                    last_error = exc
                    time.sleep(0.5 * attempt)
                    continue
                raise SupabaseError(
                    f"Cannot reach {self.url}: {exc.reason}. Check SUPABASE_URL and your network."
                ) from exc
        raise SupabaseError(f"Supabase request failed after {MAX_ATTEMPTS} attempts: {last_error}")

    # ------------------------------------------------------------------ API

    def select(self, table: str, *, columns: str = "*", filters=None,
               order: str | None = None, limit: int | None = None) -> list[dict]:
        """Read rows from a table.

        `filters` maps a column to a PostgREST operator string, e.g.
        `{"roll_no": "eq.22CS045"}`. A column may also map to a *list* of
        operators, which is how a range is expressed: PostgREST reads
        `holiday_date=gte.X&holiday_date=lte.Y` as two conditions on one column.
        Collapsing those into a single dict entry silently drops one of them.
        """
        pairs: list[tuple[str, str]] = [("select", columns)]
        for column, condition in (filters or {}).items():
            for one in (condition if isinstance(condition, (list, tuple)) else [condition]):
                pairs.append((column, one))
        if order:
            pairs.append(("order", order))
        if limit is not None:
            pairs.append(("limit", str(limit)))
        rows = self._send("GET", table, query=urllib.parse.urlencode(pairs))
        return rows or []

    def rpc(self, function: str, args: dict | None = None):
        """Call a stored procedure. Returns whatever the function returns:
        a scalar, an object, or a list of rows."""
        return self._send("POST", f"rpc/{function}", body=args or {})

    def healthcheck(self) -> dict:
        """Prove the URL, the key and the migration are all in place."""
        return self.rpc("healthcheck")
