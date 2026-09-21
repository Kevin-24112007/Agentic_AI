"""Verify a Supabase project is ready before pointing the agent at it.

    python -m scripts.cloud_check

Checks that SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are set, that
schema/supabase.sql has been run, that the seed data is present, and that
anonymous access is actually blocked (Row Level Security doing its job).
"""
import os

from app.supabase_client import SupabaseClient, SupabaseError


def main() -> None:
    if not os.environ.get("SUPABASE_URL") or not os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        raise SystemExit(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are not set.\n"
            "Copy .env.example to .env, fill in your project's values, and try again."
        )

    client = SupabaseClient()

    try:
        client.healthcheck()
    except SupabaseError as exc:
        raise SystemExit(
            f"Could not reach the migration's healthcheck() function.\n{exc}\n"
            "Has schema/supabase.sql been run in the SQL Editor yet?"
        ) from exc

    students = client.rpc("table_count", {"p_table": "leave_student"})
    holidays = client.rpc("table_count", {"p_table": "leave_holiday"})
    policies = client.rpc("table_count", {"p_table": "leave_policy"})
    print(f"students seeded:  {students}")
    print(f"holidays seeded:  {holidays}")
    print(f"policies seeded:  {policies}")
    if not (students and holidays and policies):
        raise SystemExit("Seed data is missing. Re-run schema/supabase.sql.")

    print(f"agent runtime reachable: {client.rpc('table_count', {'p_table': 'agent_thread'}) is not None}")

    anon_key = os.environ.get("SUPABASE_ANON_KEY")
    if anon_key:
        anon = SupabaseClient(key=anon_key)
        try:
            anon.select("leave_student", columns="id", limit=1)
        except SupabaseError:
            print("RLS check: anon key correctly refused (good).")
        else:
            print("RLS check: WARNING - the anon key could read leave_student. "
                  "Check that Row Level Security is enabled with no policies.")
    else:
        print("RLS check skipped (no SUPABASE_ANON_KEY set to test with).")

    print("PASS: Supabase schema is reachable and seeded.")


if __name__ == "__main__":
    main()
