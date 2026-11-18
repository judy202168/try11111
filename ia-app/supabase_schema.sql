-- JD's SOX/IA AI Lab — Supabase persistence schema
-- The application uses a server-only random token in X-IA-Token. Only its SHA-256
-- hash is stored in private.ia_access_tokens. Never commit or insert the raw token here.

create schema if not exists private;

create table if not exists private.ia_access_tokens (
  workspace_key text primary key,
  token_sha256 text not null check (token_sha256 ~ '^[0-9a-f]{64}$'),
  created_at timestamptz not null default now(),
  rotated_at timestamptz not null default now()
);

revoke all on schema private from public, anon, authenticated;
revoke all on all tables in schema private from public, anon, authenticated;

create or replace function private.ia_request_authorized(target_workspace text)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from private.ia_access_tokens token
    where token.workspace_key = target_workspace
      and token.token_sha256 = encode(
        extensions.digest(
          coalesce(current_setting('request.headers', true)::jsonb ->> 'x-ia-token', ''),
          'sha256'
        ),
        'hex'
      )
  );
$$;

revoke all on function private.ia_request_authorized(text) from public;
grant usage on schema private to anon, authenticated, service_role;
grant execute on function private.ia_request_authorized(text) to anon, authenticated, service_role;

create table if not exists public.ia_workspace_state (
  workspace_key text primary key,
  data jsonb not null default '{}'::jsonb check (jsonb_typeof(data) = 'object'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.ia_workspace_state enable row level security;
alter table public.ia_workspace_state force row level security;

revoke all on table public.ia_workspace_state from anon, authenticated;
grant select, insert, update on table public.ia_workspace_state to anon, authenticated;

drop policy if exists "server token can read workspace" on public.ia_workspace_state;
create policy "server token can read workspace"
on public.ia_workspace_state for select
to anon, authenticated
using ((select private.ia_request_authorized(workspace_key)));

drop policy if exists "server token can insert workspace" on public.ia_workspace_state;
create policy "server token can insert workspace"
on public.ia_workspace_state for insert
to anon, authenticated
with check ((select private.ia_request_authorized(workspace_key)));

drop policy if exists "server token can update workspace" on public.ia_workspace_state;
create policy "server token can update workspace"
on public.ia_workspace_state for update
to anon, authenticated
using ((select private.ia_request_authorized(workspace_key)))
with check ((select private.ia_request_authorized(workspace_key)));

create or replace function private.set_ia_workspace_updated_at()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

revoke all on function private.set_ia_workspace_updated_at() from public, anon, authenticated;

drop trigger if exists ia_workspace_updated_at on public.ia_workspace_state;
create trigger ia_workspace_updated_at
before update on public.ia_workspace_state
for each row execute function private.set_ia_workspace_updated_at();

-- No delete grant or policy is provided. Workspace deletion requires an explicit
-- administrative database action rather than a public Data API request.
