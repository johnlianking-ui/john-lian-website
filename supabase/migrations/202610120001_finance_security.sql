-- Apply through Supabase SQL Editor as database owner, before enabling real payments.
-- Does not recalculate historical balances or configure reward/Task 6 amounts.
begin;

revoke create on schema public from public, anon, authenticated;

-- Remove direct browser writes, including existing column-level grants.
do $$
declare t text; columns_sql text;
begin
  foreach t in array array['Tasks','account_balances','deposits','withdrawals','task_submissions','internal_transfers','profiles','referrals'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on table public.%I from public, anon, authenticated', t);
    select string_agg(quote_ident(column_name), ', ' order by ordinal_position)
      into columns_sql from information_schema.columns
      where table_schema = 'public' and table_name = t;
    execute format('revoke select (%s), insert (%s), update (%s), references (%s) on public.%I from public, anon, authenticated',
      columns_sql, columns_sql, columns_sql, columns_sql, t);
    execute format('grant select on public.%I to authenticated', t);
  end loop;
end $$;

grant insert (user_id, amount, payment_method, status) on public.deposits to authenticated;
grant insert (user_id, amount, payment_method) on public.withdrawals to authenticated;
grant insert (user_id, task_id, proof_text, proof_image_url, status) on public.task_submissions to authenticated;

do $$
declare sequence_name text; p record;
begin
  sequence_name := pg_get_serial_sequence('public.task_submissions', 'id');
  if sequence_name is not null then
    execute format('revoke all on sequence %s from public, anon, authenticated', sequence_name);
    execute format('grant usage on sequence %s to authenticated', sequence_name);
  end if;
  -- Policies are permissive/ORed; remove all old write policies on these tables.
  for p in select schemaname, tablename, policyname from pg_policies
    where schemaname = 'public'
      and tablename in ('deposits','withdrawals','task_submissions','internal_transfers','referrals')
      and cmd in ('INSERT','UPDATE','DELETE','ALL')
  loop
    execute format('drop policy %I on %I.%I', p.policyname, p.schemaname, p.tablename);
  end loop;
end $$;

create policy "Clients submit pending deposits" on public.deposits for insert to authenticated
  with check (user_id = auth.uid() and status = 'pending');
create policy "Clients submit pending withdrawals" on public.withdrawals for insert to authenticated
  with check (user_id = auth.uid() and status = 'pending');
create policy "Clients submit pending task proof" on public.task_submissions for insert to authenticated
  with check (user_id = auth.uid() and status = 'pending' and reviewed_at is null
    and split_part(proof_image_url, '/', 1) = auth.uid()::text
    and exists (select 1 from public."Tasks" t where t.id = task_id and t.status = 'active'));

drop policy if exists "Users can view their own transfers" on public.internal_transfers;
create policy "Users can view their own transfers" on public.internal_transfers for select to authenticated
  using (auth.uid() = sender_id or auth.uid() = recipient_id);

-- NOT VALID leaves historical rows intact while protecting every new write.
do $$
declare t text;
begin
  foreach t in array array['deposits','withdrawals','internal_transfers'] loop
    if not exists (select 1 from pg_constraint where conrelid = format('public.%I', t)::regclass and conname = 'valid_payment_amount') then
      execute format('alter table public.%I add constraint valid_payment_amount check
        (status = ''rejected'' or (amount > 0 and amount::text not in (''NaN'', ''Infinity'', ''-Infinity'') and amount = round(amount, 2))) not valid', t);
    end if;
  end loop;
  if not exists (select 1 from pg_constraint where conrelid = 'public.account_balances'::regclass and conname = 'valid_account_balance') then
    alter table public.account_balances add constraint valid_account_balance
      check (balance >= 0 and balance::text not in ('NaN', 'Infinity', '-Infinity')) not valid;
  end if;
end $$;

create or replace function public.approve_deposit(deposit_id uuid)
returns void language plpgsql security definer set search_path = '' as $$
declare request public.deposits%rowtype;
begin
  if auth.uid() is null or (auth.jwt()->'app_metadata'->>'role') is distinct from 'admin' then
    raise exception 'Only admins can approve deposits.';
  end if;
  select * into request from public.deposits where id = deposit_id for update;
  if not found then raise exception 'Deposit not found.'; end if;
  if request.status is distinct from 'pending' then raise exception 'This deposit has already been processed.'; end if;
  if request.amount is null or request.amount <= 0 or request.amount::text in ('NaN','Infinity','-Infinity') or request.amount <> round(request.amount, 2) then
    raise exception 'Invalid deposit amount.';
  end if;
  insert into public.account_balances(user_id, balance) values(request.user_id, 0) on conflict(user_id) do nothing;
  update public.account_balances set balance = balance + request.amount, updated_at = now() where user_id = request.user_id;
  update public.deposits set status = 'approved' where id = deposit_id;
end $$;

create or replace function public.approve_withdrawal(withdrawal_id uuid)
returns void language plpgsql security definer set search_path = '' as $$
declare request public.withdrawals%rowtype; available numeric;
begin
  if auth.uid() is null or (auth.jwt()->'app_metadata'->>'role') is distinct from 'admin' then
    raise exception 'Only admins can approve withdrawals.';
  end if;
  select * into request from public.withdrawals where id = withdrawal_id for update;
  if not found then raise exception 'Withdrawal not found.'; end if;
  if request.status is distinct from 'pending' then raise exception 'This withdrawal has already been processed.'; end if;
  if request.amount is null or request.amount <= 0 or request.amount::text in ('NaN','Infinity','-Infinity') or request.amount <> round(request.amount, 2) then
    raise exception 'Invalid withdrawal amount.';
  end if;
  select balance into available from public.account_balances where user_id = request.user_id for update;
  if available is null or available::text in ('NaN','Infinity','-Infinity') or available < request.amount then
    raise exception 'Insufficient available balance.';
  end if;
  update public.account_balances set balance = balance - request.amount, updated_at = now() where user_id = request.user_id;
  update public.withdrawals set status = 'approved' where id = withdrawal_id;
end $$;

create or replace function public.approve_task_submission(submission_id bigint)
returns void language plpgsql security definer set search_path = '' as $$
declare request public.task_submissions%rowtype; task_reward numeric;
begin
  if auth.uid() is null or (auth.jwt()->'app_metadata'->>'role') is distinct from 'admin' then
    raise exception 'Only admins can approve task submissions.';
  end if;
  select * into request from public.task_submissions where id = submission_id for update;
  if not found then raise exception 'Task submission not found.'; end if;
  if request.status is distinct from 'pending' then raise exception 'This task submission has already been processed.'; end if;
  -- Two different submissions of the same task must never pay twice.
  perform pg_advisory_xact_lock(hashtextextended(request.user_id::text || ':' || request.task_id::text, 0));
  if exists (select 1 from public.task_submissions s where s.user_id = request.user_id and s.task_id = request.task_id and s.status = 'approved') then
    raise exception 'This task has already been rewarded for this user.';
  end if;
  -- STRICT also refuses ambiguous task IDs in the legacy composite primary key.
  select reward into strict task_reward from public."Tasks" where id = request.task_id;
  if task_reward is null or task_reward < 0 or task_reward::text in ('NaN','Infinity','-Infinity') or task_reward <> round(task_reward, 2) then
    raise exception 'Invalid task reward.';
  end if;
  insert into public.account_balances(user_id, balance) values(request.user_id, 0) on conflict(user_id) do nothing;
  update public.account_balances set balance = balance + task_reward, updated_at = now() where user_id = request.user_id;
  update public.task_submissions set status = 'approved', reviewed_at = now() where id = submission_id;
end $$;

create or replace function public.create_internal_transfer(recipient_reference text, transfer_amount numeric)
returns uuid language plpgsql security definer set search_path = public, pg_temp as $$
declare sender uuid := auth.uid(); recipient uuid; available numeric; result_id uuid;
begin
  if sender is null then raise exception 'You must be logged in.'; end if;
  if transfer_amount is null or transfer_amount <= 0 or transfer_amount::text in ('NaN','Infinity','-Infinity') or transfer_amount <> round(transfer_amount, 2) then
    raise exception 'Invalid transfer amount.';
  end if;
  if recipient_reference is null or btrim(recipient_reference) = '' then raise exception 'Recipient reference is required.'; end if;
  recipient := public.find_user_by_reference(recipient_reference);
  if recipient is null then raise exception 'Recipient not found.'; end if;
  if recipient = sender then raise exception 'You cannot transfer funds to yourself.'; end if;
  -- Create/lock both balances in the same order, including opposite-direction transfers.
  insert into public.account_balances(user_id, balance)
    select u.id, 0 from auth.users u where u.id in (sender, recipient) order by u.id
    on conflict(user_id) do nothing;
  perform 1 from public.account_balances where user_id in (sender, recipient) order by user_id for update;
  select balance into available from public.account_balances where user_id = sender;
  if available is null or available::text in ('NaN','Infinity','-Infinity') or available < transfer_amount then
    raise exception 'Insufficient available balance.';
  end if;
  if not exists (select 1 from public.account_balances where user_id = recipient) then raise exception 'Recipient not found.'; end if;
  update public.account_balances set balance = balance - transfer_amount, updated_at = now() where user_id = sender;
  update public.account_balances set balance = balance + transfer_amount, updated_at = now() where user_id = recipient;
  insert into public.internal_transfers(sender_id, recipient_id, recipient_reference, amount, status)
    values(sender, recipient, upper(btrim(recipient_reference)), transfer_amount, 'completed') returning id into result_id;
  return result_id;
end $$;

create or replace function public.reject_deposit(deposit_id uuid)
returns void language plpgsql security definer set search_path = '' as $$
begin
  if auth.uid() is null or (auth.jwt()->'app_metadata'->>'role') is distinct from 'admin' then raise exception 'Only admins can reject deposits.'; end if;
  update public.deposits set status = 'rejected' where id = deposit_id and status = 'pending';
  if not found then raise exception 'Deposit not found or already processed.'; end if;
end $$;

create or replace function public.reject_withdrawal(withdrawal_id uuid)
returns void language plpgsql security definer set search_path = '' as $$
begin
  if auth.uid() is null or (auth.jwt()->'app_metadata'->>'role') is distinct from 'admin' then raise exception 'Only admins can reject withdrawals.'; end if;
  update public.withdrawals set status = 'rejected' where id = withdrawal_id and status = 'pending';
  if not found then raise exception 'Withdrawal not found or already processed.'; end if;
end $$;

create or replace function public.reject_task_submission(submission_id bigint)
returns void language plpgsql security definer set search_path = '' as $$
begin
  if auth.uid() is null or (auth.jwt()->'app_metadata'->>'role') is distinct from 'admin' then raise exception 'Only admins can reject tasks.'; end if;
  update public.task_submissions set status = 'rejected', reviewed_at = now() where id = submission_id and status = 'pending';
  if not found then raise exception 'Submission not found or already processed.'; end if;
end $$;

-- Remove anonymous execution, including grants inherited through PUBLIC.
revoke all on function public.approve_deposit(uuid), public.approve_withdrawal(uuid),
  public.approve_task_submission(bigint), public.create_internal_transfer(text,numeric),
  public.reject_deposit(uuid), public.reject_withdrawal(uuid), public.reject_task_submission(bigint)
  from public, anon, authenticated;
grant execute on function public.approve_deposit(uuid), public.approve_withdrawal(uuid),
  public.approve_task_submission(bigint), public.create_internal_transfer(text,numeric),
  public.reject_deposit(uuid), public.reject_withdrawal(uuid), public.reject_task_submission(bigint)
  to authenticated;
do $$
declare helper record;
begin
  for helper in select p.oid::regprocedure as signature
    from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public' and p.proname = 'find_user_by_reference' and p.prokind = 'f'
  loop
    execute format('revoke all on function %s from public, anon, authenticated', helper.signature);
  end loop;
end $$;

-- Proof screenshots belong to their uploader and reviewing administrators.
update storage.buckets set public = false where id = 'task-proofs';
drop policy if exists "Users can view task proofs" on storage.objects;
create policy "Users can view task proofs" on storage.objects for select to authenticated
  using (bucket_id = 'task-proofs' and
    (split_part(name, '/', 1) = auth.uid()::text or (auth.jwt()->'app_metadata'->>'role') = 'admin'));

notify pgrst, 'reload schema';
commit;
