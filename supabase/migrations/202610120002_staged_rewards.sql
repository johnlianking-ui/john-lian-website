-- Apply AFTER 202610120001_finance_security.sql. No historical balances are changed.
begin;

create table if not exists public.reward_submissions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  step smallint not null check (step between 0 and 6), -- 0 = separately verified reward claim
  proof_path text,
  proof_text text not null default '' check (length(proof_text) <= 2000),
  claim_amount numeric,
  status text not null default 'pending' check (status in ('pending','approved','rejected')),
  review_note text not null default '' check (length(review_note) <= 2000),
  reviewed_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  reviewed_at timestamptz,
  check ((step = 0 and claim_amount is not null and claim_amount between 20 and 30
          and claim_amount = round(claim_amount, 2)) or (step <> 0 and claim_amount is null)),
  check (step = 6 or (proof_path is not null and split_part(proof_path, '/', 1) = user_id::text))
);
create unique index if not exists reward_one_active_submission
  on public.reward_submissions(user_id, step) where status in ('pending','approved');

create table if not exists public.reward_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  event text not null check (event in ('joining_bonus','verified_claim','tasks_4_5_bonus','pending_release')),
  available_delta numeric not null,
  pending_delta numeric not null,
  submission_id uuid not null references public.reward_submissions(id),
  created_at timestamptz not null default now(),
  unique (user_id, event),
  check ((event = 'joining_bonus' and available_delta = 100 and pending_delta = 0)
    or (event = 'verified_claim' and available_delta = 0 and pending_delta between 20 and 30 and pending_delta = round(pending_delta,2))
    or (event = 'tasks_4_5_bonus' and available_delta = 0 and pending_delta = 100)
    or (event = 'pending_release' and available_delta between 120 and 130 and pending_delta = -available_delta))
);

alter table public.reward_submissions enable row level security;
alter table public.reward_events enable row level security;
revoke all on public.reward_submissions, public.reward_events from public, anon, authenticated;
grant select on public.reward_submissions, public.reward_events to authenticated;
drop policy if exists "Read own rewards or review as admin" on public.reward_submissions;
create policy "Read own rewards or review as admin" on public.reward_submissions for select to authenticated
  using (auth.uid() = user_id or (auth.jwt()->'app_metadata'->>'role') = 'admin');
drop policy if exists "Read own reward events or review as admin" on public.reward_events;
create policy "Read own reward events or review as admin" on public.reward_events for select to authenticated
  using (auth.uid() = user_id or (auth.jwt()->'app_metadata'->>'role') = 'admin');

-- Retire new submissions to the old per-task payout flow. Historical requests remain reviewable.
revoke insert (user_id, task_id, proof_text, proof_image_url, status) on public.task_submissions from authenticated;
drop policy if exists "Clients submit pending task proof" on public.task_submissions;

-- Separate private, immutable screenshots for the new program.
insert into storage.buckets(id, name, public, file_size_limit, allowed_mime_types)
  values ('reward-proofs', 'reward-proofs', false, 5242880, array['image/png','image/jpeg','image/webp'])
  on conflict(id) do update set public = false, file_size_limit = 5242880,
    allowed_mime_types = array['image/png','image/jpeg','image/webp'];
drop policy if exists "Upload own reward proof" on storage.objects;
create policy "Upload own reward proof" on storage.objects for insert to authenticated
  with check (bucket_id = 'reward-proofs' and split_part(name,'/',1) = auth.uid()::text);
drop policy if exists "Read own reward proof or admin" on storage.objects;
create policy "Read own reward proof or admin" on storage.objects for select to authenticated
  using (bucket_id = 'reward-proofs' and (split_part(name,'/',1) = auth.uid()::text or (auth.jwt()->'app_metadata'->>'role') = 'admin'));
-- Restrictive policies also guard against unrelated permissive storage policies.
drop policy if exists "Reward proof read boundary" on storage.objects;
create policy "Reward proof read boundary" on storage.objects as restrictive for select to public
  using (bucket_id <> 'reward-proofs' or (auth.uid() is not null and
    (split_part(name,'/',1) = auth.uid()::text or (auth.jwt()->'app_metadata'->>'role') = 'admin')));
drop policy if exists "Reward proof upload boundary" on storage.objects;
create policy "Reward proof upload boundary" on storage.objects as restrictive for insert to public
  with check (bucket_id <> 'reward-proofs' or (auth.uid() is not null and split_part(name,'/',1) = auth.uid()::text));
drop policy if exists "Reward proof immutable update" on storage.objects;
create policy "Reward proof immutable update" on storage.objects as restrictive for update to public
  using (bucket_id <> 'reward-proofs') with check (bucket_id <> 'reward-proofs');
drop policy if exists "Reward proof immutable delete" on storage.objects;
create policy "Reward proof immutable delete" on storage.objects as restrictive for delete to public
  using (bucket_id <> 'reward-proofs');

-- Internal helper; callers hold the per-user lock before checking dependencies.
create or replace function public.check_reward_prerequisites(member_id uuid, task_step integer)
returns void language plpgsql security definer set search_path = '' as $$
begin
  if task_step in (0,4,5,6) and not exists (
    select 1 from public.reward_events where user_id = member_id and event = 'joining_bonus'
  ) then raise exception 'Tasks 1–3 must be approved first.'; end if;
  if task_step in (5,6) and not exists (
    select 1 from public.reward_events where user_id = member_id and event = 'verified_claim'
  ) then raise exception 'Your reward claim must be approved first.'; end if;
  if task_step = 6 and not exists (
    select 1 from public.reward_events where user_id = member_id and event = 'tasks_4_5_bonus'
  ) then raise exception 'Tasks 4 and 5 must be approved first.'; end if;
end $$;

create or replace function public.submit_reward_task(task_step integer, screenshot_path text default null,
  details text default '', claimed_amount numeric default null)
returns uuid language plpgsql security definer set search_path = '' as $$
declare member_id uuid := auth.uid(); result_id uuid;
begin
  if member_id is null then raise exception 'Please log in.'; end if;
  if task_step is null or task_step not between 0 and 6 then raise exception 'Invalid task.'; end if;
  if details is null or length(details) > 2000 then raise exception 'Details must be at most 2000 characters.'; end if;
  if task_step = 0 then
    if claimed_amount is null or claimed_amount::text in ('NaN','Infinity','-Infinity')
      or claimed_amount not between 20 and 30 or claimed_amount <> round(claimed_amount,2)
    then raise exception 'Claim an amount from 20 to 30, with at most two decimal places.'; end if;
  elsif claimed_amount is not null then raise exception 'Only the reward claim accepts an amount.';
  end if;
  if task_step <> 6 then
    if screenshot_path is null or split_part(screenshot_path,'/',1) <> member_id::text
      or not exists (select 1 from storage.objects where bucket_id = 'reward-proofs' and name = screenshot_path)
    then raise exception 'Upload your own screenshot first.'; end if;
  elsif screenshot_path is not null then raise exception 'Final verification uses your previous screenshots.';
  end if;
  perform pg_advisory_xact_lock(hashtextextended('reward-program:' || member_id::text, 0));
  perform public.check_reward_prerequisites(member_id, task_step);
  if exists (select 1 from public.reward_submissions where user_id = member_id and step = task_step and status in ('pending','approved'))
    then raise exception 'This task is already submitted or approved.'; end if;
  insert into public.reward_submissions(user_id, step, proof_path, proof_text, claim_amount)
    values(member_id, task_step, screenshot_path, details, claimed_amount) returning id into result_id;
  return result_id;
end $$;

create or replace function public.review_reward_task(request_id uuid, approve boolean, note text default '')
returns void language plpgsql security definer set search_path = '' as $$
declare request public.reward_submissions%rowtype; member_id uuid; pending_amount numeric;
begin
  if auth.uid() is null or (auth.jwt()->'app_metadata'->>'role') is distinct from 'admin'
    then raise exception 'Only admins can review rewards.'; end if;
  if approve is null or note is null or length(note) > 2000 then raise exception 'Invalid review.'; end if;
  if not approve and btrim(note) = '' then raise exception 'Explain what the client needs to correct.'; end if;
  select user_id into member_id from public.reward_submissions where id = request_id;
  if not found then raise exception 'Submission not found.'; end if;
  if member_id = auth.uid() then raise exception 'Another admin must review your submissions.'; end if;
  -- Serialize every stage for this user, including simultaneous last screenshots/retries.
  perform pg_advisory_xact_lock(hashtextextended('reward-program:' || member_id::text, 0));
  select * into request from public.reward_submissions where id = request_id for update;
  if request.status <> 'pending' then raise exception 'Submission already reviewed.'; end if;
  if approve then perform public.check_reward_prerequisites(member_id, request.step); end if;
  update public.reward_submissions set status = case when approve then 'approved' else 'rejected' end,
    review_note = btrim(note), reviewed_at = now(), reviewed_by = auth.uid() where id = request_id;
  if not approve then return; end if;

  if request.step between 1 and 3 and
    (select count(*) from public.reward_submissions where user_id = member_id and step between 1 and 3 and status = 'approved') = 3 then
    insert into public.reward_events(user_id,event,available_delta,pending_delta,submission_id)
      values(member_id,'joining_bonus',100,0,request_id);
    insert into public.account_balances(user_id,balance) values(member_id,100)
      on conflict(user_id) do update set balance = public.account_balances.balance + 100, updated_at = now();
  elsif request.step = 0 then
    insert into public.reward_events(user_id,event,available_delta,pending_delta,submission_id)
      values(member_id,'verified_claim',0,request.claim_amount,request_id);
  elsif request.step in (4,5) and
    (select count(*) from public.reward_submissions where user_id = member_id and step in (4,5) and status = 'approved') = 2 then
    insert into public.reward_events(user_id,event,available_delta,pending_delta,submission_id)
      values(member_id,'tasks_4_5_bonus',0,100,request_id);
  elsif request.step = 6 then
    select sum(pending_delta) into pending_amount from public.reward_events where user_id = member_id;
    if pending_amount is null or pending_amount not between 120 and 130 then raise exception 'Pending rewards need review.'; end if;
    insert into public.reward_events(user_id,event,available_delta,pending_delta,submission_id)
      values(member_id,'pending_release',pending_amount,-pending_amount,request_id);
    insert into public.account_balances(user_id,balance) values(member_id,pending_amount)
      on conflict(user_id) do update set balance = public.account_balances.balance + pending_amount, updated_at = now();
  end if;
end $$;

revoke all on function public.check_reward_prerequisites(uuid,integer),
  public.submit_reward_task(integer,text,text,numeric), public.review_reward_task(uuid,boolean,text)
  from public, anon, authenticated;
grant execute on function public.submit_reward_task(integer,text,text,numeric),
  public.review_reward_task(uuid,boolean,text) to authenticated;
notify pgrst, 'reload schema';
commit;
