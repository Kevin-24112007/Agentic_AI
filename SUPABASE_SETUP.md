# Supabase deployment checklist

1. **Create a project** at supabase.com. Pick any region; nothing here is
   latency-sensitive.
2. **SQL Editor → New query.** Paste the entire contents of
   `schema/supabase.sql` and run it. It creates both table namespaces
   (`leave_*`, `agent_*`), all the RPC functions, seeds the three demo
   students, and turns on Row Level Security. It's safe to run more than
   once — every statement is `if not exists` / `or replace` / `on conflict`.
3. **Project Settings → API.** Copy two values:
   - **Project URL** → `SUPABASE_URL`
   - **service_role secret** → `SUPABASE_SERVICE_ROLE_KEY`

   Not the `anon` `public` key. RLS is on with no policies, so the anon key
   can't read anything by design — that's what makes it safe for this repo
   to be public. The service-role key bypasses RLS, which is exactly why it
   must never end up in git or in a browser.
4. **Copy the env file and fill it in:**

   ```bash
   cp .env.example .env
   ```

   ```dotenv
   STORAGE_BACKEND=supabase
   SUPABASE_URL=https://YOUR_PROJECT.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=YOUR_SERVICE_ROLE_KEY
   ```

   `.env` is gitignored. `app/config.py` reads it on startup, so nothing
   needs exporting by hand.
5. **Verify:**

   ```bash
   python -m scripts.cloud_check
   ```

   This checks the URL and key are set, that `healthcheck()` responds, that
   the three seed tables have rows, and (if you also set
   `SUPABASE_ANON_KEY`) that the anon key is correctly refused.
6. **Run the cloud demo:**

   ```bash
   python -m scripts.demo --cloud
   python -m scripts.demo --cloud --crash
   ```

## If step 5 fails

- **"SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are not set"** — `.env`
  wasn't created, or the values are still the placeholders from
  `.env.example`.
- **HTTP 401 / 403** — almost always the anon key was pasted instead of the
  service-role key. Every table has RLS on with no policies, so the anon key
  gets `permission denied` even for a plain `select`.
- **HTTP 404 on `healthcheck`** — `schema/supabase.sql` hasn't been run yet,
  or was run against a different project than the one in `SUPABASE_URL`.
- **Connection refused / timeout** — check `SUPABASE_URL` for a typo, and
  that the network in front of this machine allows outbound HTTPS.

## Design note: why one Postgres database instead of two

The brief's two-SQLite-file structure — domain data separate from agent
memory — is about keeping those concerns from leaking into each other, not
literally about file count. A Supabase project is one PostgreSQL database, so
the separation here is by table prefix and by which Python module is allowed
to touch which tables (`app/supabase_leave_db.py` never queries `agent_*`,
`app/supabase_memory.py` never queries `leave_*`). Two Supabase projects would
have given two literal databases back, at the cost of every cross-cutting
query (there are a few, in `scripts/demo.py`'s counters) needing two
connections instead of one, for no real isolation benefit in a project this
size.
