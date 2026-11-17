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
