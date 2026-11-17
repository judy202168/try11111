# Orbit CRM

A single HTML file with Tailwind CSS and inline JavaScript, served by Flask. Supabase Postgres stores contacts, opportunities, and follow-up tasks. Railway runs Flask through Gunicorn.

Features: password-protected workspace; dashboard metrics; searchable and filterable contacts; create, edit, and delete records; six-stage drag-and-drop deal pipeline; task completion and overdue filters; CSV exports; responsive layout.

## Local development

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
# Fill in the environment values, then:
set -a
source .env
set +a
.venv/bin/python app.py
```

Open http://localhost:8080. Set COOKIE_SECURE=false only for local HTTP. Production uses secure, HTTP-only session cookies. Use long random values for CRM_PASSWORD, SECRET_KEY, and CRM_DATABASE_TOKEN.

## Database

For a new project, configure and apply ../supabase_schema.sql through the Supabase plugin, then optionally run seed.sql. Run `python3 seed.py` to regenerate the deterministic seed: 24 contacts, 22 deals, 16 tasks. Seed IDs are stable, inserts are repeat-safe, and all email addresses use example.com.

The backend uses the Supabase publishable key with a separate 256-bit database token in a server-only X-CRM-Token header. Row-level security grants access to CRM tables only when the SHA-256 hash of that token matches the database's authorization function. The publishable key alone cannot access records. The CRM database token never reaches the browser. Existing Supabase tables and policies are unaffected. Set CRM_DATABASE_TOKEN and apply the matching function in auth_migration.sql together when rotating the token. This design avoids giving the Flask app a project-wide service-role key.

## Deployment

GitHub repository: https://github.com/judy202168/try11111. Both Railway services build from its main branch, using /crm as root directory and /crm/railway.toml as the configuration file. The Dockerfile installs dependencies at image build time. start.sh launches Gunicorn by default; APP_MODE=worker runs the daily agent scheduler and exits. The worker retains its hourly cron with an 8 AM America/Los_Angeles gate.

Keep secrets in Railway service variables. Web settings include SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, CRM_DATABASE_TOKEN, CRM_PASSWORD, SECRET_KEY, and OPENROUTER_API_KEY. Set COOKIE_SECURE=true in production. The scheduled worker references the web service's database and OpenRouter variables. Existing database records and credentials are preserved when changing deployment sources. APP_BUNDLE_B64 is obsolete once the GitHub build is active.

The repository root supabase_schema.sql contains the full fresh-install schema, RLS policies, and follow-up tables. Replace its SHA-256 token placeholder with the hash of your server-only CRM_DATABASE_TOKEN before provisioning a new database. Do not apply the placeholder function to the already-configured live database. Seed data is optional via seed.sql. The Flask db() helper uses Supabase REST for all persistence; JSON is used only as an API payload and a Postgres context column, never as a local storage file.

The frontend loads Tailwind's browser CDN and Google Fonts; those require internet access. Export returns all records in the current section. Monetary values are USD. This is a shared demo workspace, without per-user roles or password recovery. Login throttling is per worker and resets on restart; use shared Redis storage and individual user authentication before expanding to a multi-user production CRM.

## Tests

```sh
.venv/bin/python -m unittest discover -s tests -v
```

## Provisioned resources

- Live application: https://orbit-crm-production-ace6467a.up.railway.app
- Railway project: e5c0646b-5474-42ba-91a6-4ededee86a1a
- Railway service: 4c955ada-ab69-4741-9d28-a5203f94498f
- Railway environment: 4585cdf7-6787-4b51-9a0a-416590b161de
- Supabase project: rsppdnuciepesggjhupg (JD’s Org, us-west-1)
- Local workspace password: .access.txt (ignored by Git)

Validation: 10 backend tests plus a live integration smoke test for create, edit, persisted reads, delete, login/logout, CSRF, and denial of anonymous database access. The smoke test uses .env, creates disposable test records, then deletes only those records.

## Autonomous follow-up agent

Open **Followups** in the CRM. The dedicated Railway service `crm-morning-agent` wakes hourly and runs only at 8 AM America/Los_Angeles, including daylight-saving changes. Set OPENROUTER_API_KEY on orbit-crm; the scheduled worker references it. Default model: openai/gpt-4o-mini; change OPENROUTER_MODEL to use another OpenRouter model. STALL_DAYS defaults to 7. No key is bundled in source.

Contacts except Inactive, and deals except Won/Lost, qualify after seven days without recorded activity. Creation time is the explicit fallback where activity is unknown. Use “Record activity today” only after an actual interaction. Draft generation does not update activity time. Each run creates at most ten drafts; repeated runs skip an already-claimed entity/activity version, including rejected drafts. Failed drafts have a Retry generation action. Interrupted generating claims require administrator investigation rather than silently incurring repeat model charges.

The model receives only the selected record context, linked contact name/email/company/role, and open linked tasks. Context can be inspected in the approval queue. Drafts contain a subject, body, and suggested next action. Those suggestions are saved separately on CRM records. The model has no tools. Approval/rejection is an authenticated, CSRF-protected, conditional transition from pending with a review note and timestamp. The shared workspace has no individual reviewer identities. Approval does not send email. There is no mail client, mail credential, delivery endpoint, or automatic sending code.
