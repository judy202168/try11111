-- Fresh database setup. Replace the SHA-256 placeholder before running.
-- Existing live database is already provisioned; do not overwrite its token hash.
begin;
-- Orbit CRM: isolated tables; Flask is the only database client; auth_migration.sql installs token-checked RLS.
create table if not exists public.crm_contacts (
 id uuid primary key default gen_random_uuid(),
 name text not null check (length(trim(name)) > 0), email text not null default '',
 company text not null default '', role text not null default '', phone text not null default '',
 status text not null default 'Lead' check (status in ('Lead','Active','Customer','Inactive')),
 owner text not null default 'Alex Morgan', notes text not null default '',
 created_at timestamptz not null default now()
);
create table if not exists public.crm_deals (
 id uuid primary key default gen_random_uuid(), title text not null check(length(trim(title)) > 0),
 company text not null default '', contact_id uuid references public.crm_contacts(id) on delete set null,
 value numeric(15,2) not null default 0 check(value >= 0),
 stage text not null default 'Lead' check(stage in ('Lead','Qualified','Proposal','Negotiation','Won','Lost')),
 owner text not null default 'Alex Morgan', close_date date, notes text not null default '',
 created_at timestamptz not null default now()
);
create table if not exists public.crm_tasks (
 id uuid primary key default gen_random_uuid(), title text not null check(length(trim(title)) > 0),
 contact_id uuid references public.crm_contacts(id) on delete set null, due_date date,
 priority text not null default 'Medium' check(priority in ('Low','Medium','High')),
 done boolean not null default false, owner text not null default 'Alex Morgan',
 created_at timestamptz not null default now()
);
create index if not exists crm_deals_contact on public.crm_deals(contact_id);
create index if not exists crm_tasks_contact on public.crm_tasks(contact_id);
create index if not exists crm_tasks_due on public.crm_tasks(due_date) where not done;
alter table public.crm_contacts enable row level security;
alter table public.crm_deals enable row level security;
alter table public.crm_tasks enable row level security;
revoke all on public.crm_contacts, public.crm_deals, public.crm_tasks from anon, authenticated;
grant all on public.crm_contacts, public.crm_deals, public.crm_tasks to service_role;

-- Server-only token authorization. Token hash is safe to keep with source.
create or replace function public.crm_authorized() returns boolean
language sql stable set search_path = '' as $$
 select encode(sha256(convert_to(coalesce(current_setting('request.headers', true)::jsonb ->> 'x-crm-token',''), 'UTF8')), 'hex') = 'REPLACE_WITH_SHA256_OF_CRM_DATABASE_TOKEN';
$$;
revoke all on function public.crm_authorized() from public;
grant execute on function public.crm_authorized() to anon;
grant select, insert, update, delete on public.crm_contacts, public.crm_deals, public.crm_tasks to anon;
drop policy if exists crm_backend_contacts on public.crm_contacts;
create policy crm_backend_contacts on public.crm_contacts for all to anon using ((select public.crm_authorized())) with check ((select public.crm_authorized()));
drop policy if exists crm_backend_deals on public.crm_deals;
create policy crm_backend_deals on public.crm_deals for all to anon using ((select public.crm_authorized())) with check ((select public.crm_authorized()));
drop policy if exists crm_backend_tasks on public.crm_tasks;
create policy crm_backend_tasks on public.crm_tasks for all to anon using ((select public.crm_authorized())) with check ((select public.crm_authorized()));

alter table public.crm_contacts add column if not exists last_activity_at timestamptz;
alter table public.crm_deals add column if not exists last_activity_at timestamptz;
alter table public.crm_contacts add column if not exists suggested_next_action text;
alter table public.crm_deals add column if not exists suggested_next_action text;
create table if not exists public.crm_followups (
 id uuid primary key default gen_random_uuid(), entity_type text not null check(entity_type in ('contacts','deals')),
 entity_id uuid not null, activity_version text not null, context jsonb not null,
 subject text not null default '', body text not null default '', next_action text not null default '',
 status text not null default 'generating' check(status in ('generating','pending','approved','rejected','failed')),
 model text not null, error text, reviewed_at timestamptz, review_note text not null default '',
 created_at timestamptz not null default now(), unique(entity_type,entity_id,activity_version)
);
alter table public.crm_followups enable row level security;
grant select,insert,update on public.crm_followups to anon;
drop policy if exists crm_backend_followups on public.crm_followups;
create policy crm_backend_followups on public.crm_followups for all to anon using ((select public.crm_authorized())) with check ((select public.crm_authorized()));
create index if not exists crm_followups_status on public.crm_followups(status,created_at);

commit;

-- Evaluation tables (seed separately using crm/evaluation_seed.sql)
begin;
create table public.crm_evaluation_scenarios (
 id uuid primary key, scenario_number integer not null unique check(scenario_number in (1,5,7)),
 name text not null, business_objective text not null, risk_category text not null,
 input_context jsonb not null, expected_behavior jsonb not null,
 created_at timestamptz not null default now()
);
create table public.crm_evaluation_rules (
 id uuid primary key, scenario_id uuid not null references public.crm_evaluation_scenarios(id),
 rule_key text not null, name text not null, description text not null,
 expected jsonb not null, position integer not null,
 updated_at timestamptz not null default now(), created_at timestamptz not null default now(), unique(scenario_id,rule_key)
);
create table public.crm_evaluation_runs (
 id uuid primary key default gen_random_uuid(), batch_id uuid not null,
 scenario_id uuid not null references public.crm_evaluation_scenarios(id),
 status text not null default 'running' check(status in ('running','passed','failed','error')),
 input_snapshot jsonb not null, expected_behavior jsonb not null, rules_snapshot jsonb not null,
 proposed_output jsonb not null default '{}', failure_reason text,
 model text not null, estimated_cost_usd numeric(16,10), cost_source text not null default 'unavailable',
 response_time_ms integer, model_calls jsonb not null default '[]', agent_version text not null,
 completed_at timestamptz, created_at timestamptz not null default now()
);
create table public.crm_evaluation_check_results (
 id uuid primary key default gen_random_uuid(), run_id uuid not null references public.crm_evaluation_runs(id),
 rule_id uuid not null references public.crm_evaluation_rules(id), rule_key text not null,
 name text not null, passed boolean not null, expected jsonb not null,
 actual jsonb not null, explanation text not null, created_at timestamptz not null default now(), unique(run_id,rule_id)
);
create index crm_eval_rules_scenario on public.crm_evaluation_rules(scenario_id,position);
create index crm_eval_runs_scenario_time on public.crm_evaluation_runs(scenario_id,created_at desc);
create index crm_eval_runs_batch on public.crm_evaluation_runs(batch_id);
create index crm_eval_checks_rule on public.crm_evaluation_check_results(rule_id);
alter table public.crm_evaluation_scenarios enable row level security;
alter table public.crm_evaluation_rules enable row level security;
alter table public.crm_evaluation_runs enable row level security;
alter table public.crm_evaluation_check_results enable row level security;
grant select on public.crm_evaluation_scenarios to anon;
grant select,update on public.crm_evaluation_rules to anon;
grant select,insert,update on public.crm_evaluation_runs to anon;
grant select,insert on public.crm_evaluation_check_results to anon;
create policy evaluation_backend_scenarios on public.crm_evaluation_scenarios for select to anon using ((select public.crm_authorized()));
create policy evaluation_backend_rules on public.crm_evaluation_rules for all to anon using ((select public.crm_authorized())) with check ((select public.crm_authorized()));
create policy evaluation_backend_runs on public.crm_evaluation_runs for all to anon using ((select public.crm_authorized())) with check ((select public.crm_authorized()));
create policy evaluation_backend_checks on public.crm_evaluation_check_results for all to anon using ((select public.crm_authorized())) with check ((select public.crm_authorized()));
commit;
