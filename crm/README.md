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

GitHub repository: https://github.com/judy202168/try11111. The GitHub source is ready on main. The intended Railway source uses /crm as root directory; the reviewed settings are in ../.railway/deployment-settings.json. Both services are connected to main; pushes deploy automatically. The Dockerfile installs dependencies at image build time. start.sh launches Gunicorn by default; APP_MODE=worker runs the daily agent scheduler and exits. The worker retains its hourly cron with an 8 AM America/Los_Angeles gate.

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

The model receives only the selected record context, linked contact name/email/company/role, and open linked tasks. Context can be inspected in the approval queue. Drafts contain a subject, body, and suggested next action. Suggestions remain inside the internal approval queue; the autonomous agent no longer writes suggested actions to parent CRM records. The model has no tools. Approval/rejection is an authenticated, CSRF-protected, conditional transition from pending with a review note and timestamp. The shared workspace has no individual reviewer identities. Approval does not send email. There is no mail client, mail credential, delivery endpoint, or automatic sending code.

## Evaluation system — scenarios 1, 5, and 7

The Evaluations tab stores 3 synthetic scenarios, 17 deterministic rules, and the latest 100 run records with individual check results. “Run evaluation” runs each chosen scenario through the same followup_agent.run implementation used in production. It supplies a deep-copied in-memory database containing only that scenario and repeats the run to test idempotency. The evaluator's persistent storage closure permits only evaluation tables; it cannot access CRM contacts, deals, tasks, or drafts. Only synthetic fixture context is sent to OpenRouter, and no send mechanism is available. Production agent behavior is measured, not replaced by a special evaluation-only planner.

The suite can fail: the current agent can propose both contact and opportunity drafts, lacks a missing-email gate, and has no structured commitment-to-task extraction. Failed checks are recorded as business findings rather than silently marked passed. Deterministic semantic proxies check explicit names/opportunity titles, exact source evidence, IDs, owner fields, dates, output counts, and recipient data; they do not constitute a general semantic quality judge. For scenario 7 a proposed task must include due_date, owner, contact_id, opportunity_id (or deal_id), source_note, and meeting_date.

The four Supabase tables are crm_evaluation_scenarios, crm_evaluation_rules, crm_evaluation_runs, and crm_evaluation_check_results. They use the existing server-token RLS authorization. Apply evaluation_schema.sql then evaluation_seed.sql for an existing deployment. Both are included in the repository for reproducibility; fresh installs also have the schema in ../supabase_schema.sql. There is no foreign-key linkage from synthetic entities to production CRM IDs.

Rule descriptions and typed expected values are editable. Every run snapshots input, expected behavior, and rules, so later edits do not rewrite history. The measured check functions are fixed Python code; description changes are documentation only. Pass rate is over completed runs in the latest 100, including execution errors as unsuccessful runs. Running records are excluded; a process interruption can leave a running record visible for investigation.

Model usage is captured using a request-scoped ContextVar without altering the model’s draft response. Cost is provider-reported usage.cost when available; otherwise it is estimated from token counts and the current OpenRouter model pricing. If neither is available the UI shows Unavailable. Transport failures also record unknown cost rather than assuming a free call. Response time includes both first and replay execution plus saving checks. API generation failures produce an error run and cannot count as successful evaluation behavior.

API: GET /api/evaluations; POST /api/evaluations/run with scenario_id; PATCH /api/evaluations/rules/:id with description and typed expected JSON. Authentication and CSRF protection apply. Evaluations are manual and are not automatically invoked by the production morning scheduler.

Owner-routing checks require an explicit owner/review_owner assignment on the proposed draft. Merely mentioning an owner in model context is retained as evidence but does not count as routing. The initial OpenRouter baseline failed all three scenarios: duplicate/relevance/association gaps, missing-email handling, and absent structured commitment extraction. Live verification confirmed that production entities and follow-up records were unchanged. Browser QA verified the rule editor, scenario selection, run control, and persisted history.

## Structured business feedback loop

Followup Agent now queues both follow-ups and AI meeting updates. Every pending suggestion supports Approve, Reject, and Edit and approve. Rejection or editing requires exactly one of the eight configured reasons; the reviewer note remains optional, including for Other. Original AI content is immutable. A PostgreSQL transaction records the original, approved final version, action/reason/note, source customer/opportunity/workflow context, reviewer identity/team, model/prompt version, generation timing/cost, and timestamp, and changes the queue state atomically. Duplicate decisions are rejected. Approval stores a reviewed proposal only: there is no email transport and no automatic application of meeting tasks or CRM updates.

The workspace password remains the CRM entry gate. Individual reviewer accounts provide attribution. In Business Quality, create the first administrator with a display name, team, username, and personal password (at least eight characters). The first account bootstrap is unique. Thereafter only administrators can issue reviewer or administrator accounts. Review decisions require personal sign-in; the server resolves identity from the session and ignores client-supplied reviewer IDs. Account names and teams are administrator-managed identities, not SSO-verified employment records. Password hashes never reach the browser. Legacy decisions are explicitly excluded from structured rates rather than assigned invented reviewers/reasons. Legacy generation costs remain unavailable.

New meeting updates require a contact, an optional correctly linked opportunity, the exact meeting date, and source notes. OpenRouter proposes a summary, next action, and commitment objects with title, owner, due_date, and verbatim source_evidence. Unknown owners/dates can be null. The source evidence is validated against the notes. Proposals do not apply tasks; the reviewer may edit and approve the final structured plan with a reason.

Business Quality reports disjoint approval/rejection/edit rates, failure reasons, high-risk hallucination/owner/deadline failures, results by workflow/reviewing team/model/prompt, Pacific-time weekly trends, and recent failure evidence. Date and dimension filters are available. Personal identities are snapshotted on each decision so future staff changes do not rewrite history.

The existing hourly Railway worker generates a closed-week summary each Monday at 8 AM America/Los_Angeles, after the morning review, even if generation raises an error. Reviewers can also generate a week-to-date snapshot manually. The summary ranks the top three observed rejection/edit reasons, links supporting review IDs, explains their business risks, and recommends prompt, context-rule and evaluation changes. It is deterministic, uses no extra LLM calls, never fabricates three patterns when feedback is absent, and never changes a prompt. Duplicate snapshots for the same evidence are suppressed.

Prompt versions are immutable, per workflow. Initial follow-up v1 preserves the exact prior production system prompt; meeting-update v1 is the new workflow baseline. Improvements are draft versions until an administrator approves them. A release evaluation batch exercises synthetic scenarios 1, 5 and 7 using the candidate prompt; meeting candidates use the actual meeting proposal workflow for scenario 7 and active follow-up behavior for 1/5. Candidate overrides are request-scoped, so evaluation does not alter production prompts. Release requires an explicit administrator action and a database-verified passing batch for the exact prompt hash, current deployed code, current model, all three scenarios and all 17 canonical checks. Editable dashboard rule expectations cannot weaken the release gate. A code/model change requires a fresh batch. The current follow-up baseline fails these business checks, so prompt releases remain blocked until those gaps are addressed.

Tables: crm_reviewers, crm_prompt_versions, crm_prompt_evaluation_batches, crm_suggestion_reviews, crm_weekly_quality_summaries, plus immutable originals/metadata on crm_followups. feedback_schema.sql is an existing-deployment migration; the consolidated root schema also includes it for new projects. Review and release functions use SECURITY INVOKER and the existing server-token RLS check. No secret is embedded in source.

Validation includes named-reviewer enforcement, required reason validation, original/final retention, duplicate-review handling, reporter rates and top patterns, request-local candidate isolation, meeting idempotency, and PostgreSQL transaction tests of review persistence and the negative/positive release gates. The database test explicitly rolls back all test rows, its transaction-local authorization stub, and its temporary prompt release. It never commits a changed production prompt.

## Server-enforced guardrails

Policy version crm-guardrails-v1 is enforced independently of the system prompt. AgentStore grants the autonomous agent read access to relevant CRM resources and write access only to internal suggestions and guardrail audit entries. It has no email, external-record, task-application, activity-application or deletion authority. The server action gateway fails closed even when a client claims human approval. Content approval is not a permission token for an external effect. No external effect is currently permitted; a future integration would require a separate server-verified human authorization at the actual execution boundary. Manual CRM creation/editing remain user-initiated forms; CRM deletion is disabled both in Flask and by database triggers.

Usable AI text is constructed deterministically from verified linked contact/opportunity fields or verbatim meeting evidence. Arbitrary model prose is quarantined as raw audit evidence and is not published as usable draft text. Known missing or ambiguous contacts, companies, owners, decisions and deadlines remain null. Explicit source dates are parsed without estimating relative or ambiguous dates. Meeting commitment owners must be explicitly named in their source evidence; contact owners are not inferred to be commitment owners. Required missing data prevents generation/approval; other unknowns remain blank and flagged for review. No email draft is prepared when contact/email information is unavailable.

Every new suggestion records guardrail results before entering the review queue. Existing suggestions require a linked-information check; the queue does not show their unverified wording as usable text. Approve performs a fresh server-side source check and the database transaction requires the current policy result. It approves the grounded safe version, not the unverified raw model output. Human edits are individually attributed; unsupported structured commitment owners/dates and detected unsupported names/decisions are rejected. Free-form human-authored edits are content review only and cannot authorize any external effect. The server does not claim to semantically prove arbitrary human prose.

Guardrail events preserve input, raw proposed output, safe output, policy, action, decision, reason, missing fields, detected unsupported-field attempts and final disposition. Review events link to the immutable reviewer record. The Business Quality Guardrails section separates live and evaluation checks and shows allowed internal preparation, blocked effects, review cases, pass rate, blocks by policy, known unsupported-fact attempts, unapproved external attempts and failures. Unsupported-prose quarantine is not counted as proof of an invention attempt unless the server detects a specific unsupported field or claim.

Eight deterministic adversarial cases are stored in crm_guardrail_test_cases, with runs in crm_guardrail_test_runs and events in crm_guardrail_events. They exercise the actual capability boundary and grounding functions, not an LLM judge. Cases cover send email, create external records, delete CRM data, missing contact/company/owner, ambiguous customer decisions and missing/ambiguous deadlines. No model calls or real integrations are used during these tests. The tests and full actual behavior appear in Evaluations. Prompt release now also requires all eight guardrail cases on the current code in addition to the three business scenarios and 17 canonical checks.

Migrations: guardrail_schema.sql, guardrail_seed.sql and guardrail_policy_transactions.sql; the consolidated root schema includes these table/function definitions for fresh installations. The prior destructive smoke test was replaced with a read-only smoke test. Database transaction tests roll back their temporary rows and authorization stub. No secrets are written to audit inputs or source.
