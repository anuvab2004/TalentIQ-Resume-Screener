-- ============================================================================
-- TalentIQ - complete Supabase setup (run once in SQL Editor; safe to re-run)
-- Creates: requisitions, candidates, interview_guides, email_logs,
--          private 'resumes' storage bucket, and access rules.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1) TABLES
-- ---------------------------------------------------------------------------
create table if not exists public.requisitions (
  id                 text primary key,               -- e.g. 'req_1'
  title              text not null,
  department         text not null default '',
  jd_text            text not null default '',
  required_skills    jsonb not null default '[]'::jsonb,
  min_years          numeric not null default 0,
  required_education text not null default 'Not detected',
  created_at         timestamptz not null default now()
);

create table if not exists public.candidates (
  id               uuid primary key default gen_random_uuid(),
  req_id           text not null references public.requisitions(id) on delete cascade,
  candidate_name   text not null,
  filename         text not null default '',
  email            text not null default 'Not detected',
  phone            text not null default 'Not detected',
  education        text not null default 'Not detected',
  years_experience numeric not null default 0,
  overall_score    numeric not null default 0,
  status           text not null default 'Review',
  rationale        text not null default '',
  factors          jsonb not null default '{}'::jsonb,
  matched_skills   jsonb not null default '[]'::jsonb,
  missing_skills   jsonb not null default '[]'::jsonb,
  extra_skills     jsonb not null default '[]'::jsonb,
  fairness_audit   jsonb not null default '{}'::jsonb,
  semantic_engine  text not null default 'tfidf',
  hr_status        text not null default '—',
  resume_path      text,                             -- 'resumes/req_1/<id>_<file>' in Storage
  created_at       timestamptz not null default now()
);

create table if not exists public.interview_guides (
  id             uuid primary key default gen_random_uuid(),
  req_id         text not null references public.requisitions(id) on delete cascade,
  candidate_name text not null,
  questions      jsonb not null default '[]'::jsonb,
  created_at     timestamptz not null default now()
);

create table if not exists public.email_logs (
  id             uuid primary key default gen_random_uuid(),
  req_id         text not null references public.requisitions(id) on delete cascade,
  candidate_name text not null,
  status_message text not null default '',
  created_at     timestamptz not null default now()
);

-- If your candidates table already existed from an earlier version:
alter table public.candidates add column if not exists resume_path text;

-- The app upserts on (req_id, candidate_name); it needs these unique indexes.
create unique index if not exists candidates_req_name_key
  on public.candidates (req_id, candidate_name);
create unique index if not exists interview_guides_req_name_key
  on public.interview_guides (req_id, candidate_name);

create index if not exists candidates_req_score_idx
  on public.candidates (req_id, overall_score desc);
create index if not exists email_logs_created_idx
  on public.email_logs (created_at);

-- ---------------------------------------------------------------------------
-- 2) PRIVATE BUCKET FOR ORIGINAL RESUME FILES (10 MB per file)
--    If you use another name, set SUPABASE_RESUME_BUCKET and change it here
--    and in section 4.
-- ---------------------------------------------------------------------------
insert into storage.buckets (id, name, public, file_size_limit)
values ('resumes', 'resumes', false, 10485760)
on conflict (id) do update set public = false, file_size_limit = excluded.file_size_limit;

-- ---------------------------------------------------------------------------
-- 3) TABLE SECURITY: only signed-in users can read or write.
--    The anon key alone gets nothing. (All signed-in recruiters share one
--    workspace, matching how the app works today.)
-- ---------------------------------------------------------------------------
do $$
declare t text;
begin
  foreach t in array array['requisitions','candidates','interview_guides','email_logs'] loop
    execute format('alter table public.%I enable row level security', t);
    if not exists (
      select 1 from pg_policies
      where schemaname = 'public' and tablename = t and policyname = 'talentiq authenticated access'
    ) then
      execute format(
        'create policy "talentiq authenticated access" on public.%I
           for all to authenticated using (true) with check (true)', t);
    end if;
  end loop;
end $$;

-- ---------------------------------------------------------------------------
-- 4) STORAGE SECURITY: signed-in users can upload / read / replace / remove
--    files in the resumes bucket ("update" is needed because uploads use upsert).
-- ---------------------------------------------------------------------------
do $$
declare
  p record;
begin
  for p in
    select * from (values
      ('talentiq resumes insert', 'insert'),
      ('talentiq resumes select', 'select'),
      ('talentiq resumes update', 'update'),
      ('talentiq resumes delete', 'delete')
    ) as v(name, cmd)
  loop
    if not exists (
      select 1 from pg_policies
      where schemaname = 'storage' and tablename = 'objects' and policyname = p.name
    ) then
      if p.cmd = 'insert' then
        execute format('create policy %I on storage.objects for insert to authenticated
                        with check (bucket_id = ''resumes'')', p.name);
      elsif p.cmd = 'update' then
        execute format('create policy %I on storage.objects for update to authenticated
                        using (bucket_id = ''resumes'') with check (bucket_id = ''resumes'')', p.name);
      else
        execute format('create policy %I on storage.objects for %s to authenticated
                        using (bucket_id = ''resumes'')', p.name, p.cmd);
      end if;
    end if;
  end loop;
end $$;