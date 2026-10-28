-- PinkyDocs AI initial schema. Run once in Supabase SQL Editor.
-- The Python server uses the service-role key. RLS is enabled and has no
-- anonymous/authenticated policies; ownership checks are enforced in Python.

create extension if not exists pgcrypto;

create table if not exists public.app_users (
    id uuid primary key default gen_random_uuid(),
    username text not null unique
        check (username = lower(username) and username ~ '^[a-z0-9_.-]{3,24}$'),
    password_hash text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.documents (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.app_users(id) on delete cascade,
    original_filename text not null,
    display_name text not null,
    file_type text not null check (file_type in ('pdf', 'txt', 'pasted')),
    file_size_bytes bigint not null check (file_size_bytes > 0),
    storage_path text not null unique,
    content_hash text not null check (content_hash ~ '^[a-f0-9]{64}$'),
    page_count integer check (page_count is null or page_count >= 0),
    created_at timestamptz not null default now(),
    unique (user_id, id)
);
create index if not exists documents_user_created_idx
    on public.documents(user_id, created_at desc);

create table if not exists public.document_chunks (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null,
    user_id uuid not null,
    chunk_index integer not null check (chunk_index >= 0),
    content text not null check (length(content) > 0),
    page_start integer,
    page_end integer,
    line_start integer,
    line_end integer,
    section_title text,
    created_at timestamptz not null default now(),
    unique (document_id, chunk_index),
    foreign key (user_id, document_id)
        references public.documents(user_id, id) on delete cascade,
    check (page_start is null or page_start > 0),
    check (page_end is null or page_end >= page_start),
    check (line_start is null or line_start > 0),
    check (line_end is null or line_end >= line_start)
);
create index if not exists document_chunks_user_doc_idx
    on public.document_chunks(user_id, document_id, chunk_index);

create table if not exists public.conversations (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.app_users(id) on delete cascade,
    title text not null check (length(title) between 1 and 100),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (user_id, id)
);
create index if not exists conversations_user_updated_idx
    on public.conversations(user_id, updated_at desc);

create table if not exists public.conversation_documents (
    user_id uuid not null,
    conversation_id uuid not null,
    document_id uuid not null,
    created_at timestamptz not null default now(),
    primary key (conversation_id, document_id),
    foreign key (user_id, conversation_id)
        references public.conversations(user_id, id) on delete cascade,
    foreign key (user_id, document_id)
        references public.documents(user_id, id) on delete cascade
);

create table if not exists public.messages (
    id uuid primary key default gen_random_uuid(),
    conversation_id uuid not null,
    user_id uuid not null,
    role text not null check (role in ('user', 'assistant')),
    content text not null check (length(content) > 0),
    citations jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now(),
    foreign key (user_id, conversation_id)
        references public.conversations(user_id, id) on delete cascade
);
create index if not exists messages_conversation_created_idx
    on public.messages(user_id, conversation_id, created_at);

-- Each request reserves both user and global quota in one database transaction.
-- The all-day advisory lock makes the read/check/increment sequence atomic.
create table if not exists public.daily_usage (
    usage_day date not null,
    user_id uuid not null,
    question_count integer not null default 0 check (question_count >= 0),
    primary key (usage_day, user_id)
);

create table if not exists public.login_attempts (
    id bigint generated always as identity primary key,
    normalized_username text not null,
    attempted_at timestamptz not null default now()
);
create index if not exists login_attempts_username_time_idx
    on public.login_attempts(normalized_username, attempted_at desc);

create or replace function public.reserve_question(
    p_user_id uuid,
    p_day date,
    p_user_limit integer,
    p_global_limit integer
) returns void
language plpgsql
security invoker
set search_path = ''
as $$
declare
    global_id constant uuid := '00000000-0000-0000-0000-000000000000';
    user_count integer;
    global_count integer;
begin
    if p_user_id is null or p_user_id = global_id or p_user_limit < 1 or p_global_limit < 1 then
        raise exception 'INVALID_USAGE_RESERVATION';
    end if;
    perform pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtext('pinkydocs_usage'),
        pg_catalog.hashtext(p_day::text)
    );
    select coalesce((select question_count from public.daily_usage
                     where usage_day = p_day and user_id = p_user_id), 0)
      into user_count;
    select coalesce((select question_count from public.daily_usage
                     where usage_day = p_day and user_id = global_id), 0)
      into global_count;
    if user_count >= p_user_limit then
        raise exception 'USER_DAILY_LIMIT';
    end if;
    if global_count >= p_global_limit then
        raise exception 'GLOBAL_DAILY_LIMIT';
    end if;
    insert into public.daily_usage as usage_counter(usage_day, user_id, question_count)
      values (p_day, p_user_id, 1)
      on conflict (usage_day, user_id)
      do update set question_count = usage_counter.question_count + 1;
    insert into public.daily_usage as usage_counter(usage_day, user_id, question_count)
      values (p_day, global_id, 1)
      on conflict (usage_day, user_id)
      do update set question_count = usage_counter.question_count + 1;
end;
$$;

-- Rate-limit all login submissions by normalized username. The fifth attempt
-- in a 15-minute window is allowed; later attempts are rejected until expiry.
create or replace function public.reserve_login_attempt(p_username text)
returns boolean
language plpgsql
security invoker
set search_path = ''
as $$
declare
    recent_count integer;
    normalized text := pg_catalog.lower(pg_catalog.btrim(p_username));
begin
    if normalized is null or length(normalized) > 24 then
        return false;
    end if;
    perform pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtext('pinkydocs_login'),
        pg_catalog.hashtext(normalized)
    );
    delete from public.login_attempts
      where attempted_at < pg_catalog.now() - interval '15 minutes';
    select count(*) into recent_count from public.login_attempts
      where normalized_username = normalized
        and attempted_at >= pg_catalog.now() - interval '15 minutes';
    if recent_count >= 5 then
        return false;
    end if;
    insert into public.login_attempts(normalized_username) values (normalized);
    return true;
end;
$$;

create or replace function public.clear_login_attempts(p_username text)
returns void
language sql
security invoker
set search_path = ''
as $$
    delete from public.login_attempts
      where normalized_username = pg_catalog.lower(pg_catalog.btrim(p_username));
$$;

-- Private bucket; storage paths are generated by the server as user/doc/original.ext.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('documents', 'documents', false, 10485760, array['application/pdf', 'text/plain'])
on conflict (id) do update set
    public = false,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

alter table public.app_users enable row level security;
alter table public.documents enable row level security;
alter table public.document_chunks enable row level security;
alter table public.conversations enable row level security;
alter table public.conversation_documents enable row level security;
alter table public.messages enable row level security;
alter table public.daily_usage enable row level security;
alter table public.login_attempts enable row level security;

-- No anon/authenticated policies are intentionally created. Only the trusted
-- server's service-role client accesses these tables and RPCs.
revoke all on public.app_users, public.documents, public.document_chunks,
    public.conversations, public.conversation_documents, public.messages,
    public.daily_usage, public.login_attempts from anon, authenticated;
grant all on public.app_users, public.documents, public.document_chunks,
    public.conversations, public.conversation_documents, public.messages,
    public.daily_usage, public.login_attempts to service_role;
grant usage, select on sequence public.login_attempts_id_seq to service_role;
revoke all on function public.reserve_question(uuid, date, integer, integer) from public, anon, authenticated;
revoke all on function public.reserve_login_attempt(text) from public, anon, authenticated;
revoke all on function public.clear_login_attempts(text) from public, anon, authenticated;
grant execute on function public.reserve_question(uuid, date, integer, integer) to service_role;
grant execute on function public.reserve_login_attempt(text) to service_role;
grant execute on function public.clear_login_attempts(text) to service_role;
