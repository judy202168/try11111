begin;
alter table public.crm_followups add column guardrail_result jsonb;
create table public.crm_guardrail_test_cases (
 id uuid primary key, case_number integer not null unique check(case_number between 1 and 8), name text not null,
 business_risk text not null, input_context jsonb not null, proposed_output jsonb not null,
 expected_behavior jsonb not null, created_at timestamptz not null default now()
);
create table public.crm_guardrail_events (
 id uuid primary key default gen_random_uuid(), suggestion_id uuid references public.crm_followups(id),
 review_id uuid references public.crm_suggestion_reviews(id), test_case_id uuid references public.crm_guardrail_test_cases(id),
 source text not null check(source in ('production','evaluation')), guardrail text not null,
 policy_version text not null, verification_context jsonb not null default '{}', model_input jsonb not null, proposed_output jsonb not null, safe_output jsonb not null,
 proposed_action text not null, verdict text not null check(verdict in ('allowed','blocked','review')),
 status text not null, reason text not null, missing_information jsonb not null default '[]',
 invention_attempts jsonb not null default '[]', final_action text not null,
 enforced boolean not null, passed boolean not null, external_changes integer not null check(external_changes=0),
 created_at timestamptz not null default now()
);
create table public.crm_guardrail_test_runs (
 id uuid primary key default gen_random_uuid(), case_id uuid not null references public.crm_guardrail_test_cases(id),
 event_id uuid not null references public.crm_guardrail_events(id), batch_id uuid references public.crm_prompt_evaluation_batches(id),
 input_context jsonb not null, proposed_output jsonb not null, expected_behavior jsonb not null,
 actual_behavior jsonb not null, guardrail text not null, passed boolean not null, failure_explanation text,
 response_time_ms integer not null, model text not null default 'Not used: deterministic server policy test',
 estimated_cost_usd numeric(16,10) not null default 0, agent_version text not null, policy_version text not null,
 created_at timestamptz not null default now()
);
create index crm_guard_events_suggestion on public.crm_guardrail_events(suggestion_id);
create index crm_guard_events_review on public.crm_guardrail_events(review_id);
create index crm_guard_events_case on public.crm_guardrail_events(test_case_id);
create index crm_guard_events_time on public.crm_guardrail_events(source,created_at desc);
create index crm_guard_runs_case on public.crm_guardrail_test_runs(case_id,created_at desc);
create index crm_guard_runs_batch on public.crm_guardrail_test_runs(batch_id);
alter table public.crm_guardrail_test_cases enable row level security;
alter table public.crm_guardrail_events enable row level security;
alter table public.crm_guardrail_test_runs enable row level security;
grant select on public.crm_guardrail_test_cases to anon;
grant select,insert on public.crm_guardrail_events,public.crm_guardrail_test_runs to anon;
create policy crm_guard_cases_backend on public.crm_guardrail_test_cases for select to anon using ((select public.crm_authorized()));
create policy crm_guard_events_backend on public.crm_guardrail_events for all to anon using ((select public.crm_authorized())) with check ((select public.crm_authorized()));
create policy crm_guard_runs_backend on public.crm_guardrail_test_runs for all to anon using ((select public.crm_authorized())) with check ((select public.crm_authorized()));
create function public.crm_prevent_deletion() returns trigger language plpgsql set search_path='' as $$
begin raise exception 'CRM deletion is disabled by server policy'; end $$;
create trigger crm_no_contact_delete before delete on public.crm_contacts for each row execute function public.crm_prevent_deletion();
create trigger crm_no_deal_delete before delete on public.crm_deals for each row execute function public.crm_prevent_deletion();
create trigger crm_no_task_delete before delete on public.crm_tasks for each row execute function public.crm_prevent_deletion();
create trigger crm_no_suggestion_delete before delete on public.crm_followups for each row execute function public.crm_prevent_deletion();
commit;
