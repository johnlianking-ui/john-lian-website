"""Run in a disposable container only; imports the legacy finance regression first.

DOCKER_HOST=... FINANCE_TEST_CONTAINER=john-lian-rewards-test python3 supabase/tests/test_staged_rewards.py
Synthetic SQL auth/storage adapters; no hosted Supabase or payment provider calls.
"""
from decimal import Decimal
import sys

sys.dont_write_bytecode = True
import test_finance_security as base

sql, client, session, racing = base.sql, base.client, base.session, base.racing
ADMIN = base.ADMIN
C = '44444444-4444-4444-8444-444444444444'
D = '55555555-5555-4555-8555-555555555555'
E = '66666666-6666-4666-8666-666666666666'
F = '77777777-7777-4777-8777-777777777777'
legacy_balance = base.balance()
legacy_submissions = sql('SELECT count(*) FROM task_submissions;')
migration = (base.ROOT / 'supabase/migrations/202610120002_staged_rewards.sql').read_text()
sql(migration)
sql(migration)
assert base.balance() == legacy_balance
assert sql('SELECT count(*) FROM task_submissions;') == legacy_submissions
assert sql('SELECT count(*) FROM reward_events;') == '0'
for user in (C, D, E, F):
    sql(f"INSERT INTO auth.users(id,email) VALUES('{user}','{user[:8]}@example.invalid');")
    client(f"INSERT INTO storage.objects(bucket_id,name) VALUES('reward-proofs','{user}/proof.png');", user=user)
assert sql("SELECT public FROM storage.buckets WHERE id='reward-proofs';") == 'f'
assert sql("SELECT file_size_limit FROM storage.buckets WHERE id='reward-proofs';") == '5242880'


def submit(user, step, amount='NULL', error=None):
    path = 'NULL' if step == 6 else f"'{user}/proof.png'"
    result = client(f"SELECT submit_reward_task({step},{path},'Synthetic proof',{amount});", user=user, error=error)
    return result.splitlines()[-1] if result else None


def review(request, approve=True, note='', error=None):
    return client(f"SELECT review_reward_task('{request}',{str(approve).lower()},'{note}');", user=ADMIN, admin=True, error=error)


def pending(user):
    return Decimal(sql(f"SELECT coalesce(sum(pending_delta),0) FROM reward_events WHERE user_id='{user}';"))


def balance(user):
    return Decimal(sql(f"SELECT coalesce((SELECT balance FROM account_balances WHERE user_id='{user}'),0);"))


def stage_one(user):
    ids = [submit(user, step) for step in (1, 2, 3)]
    assert balance(user) == 0
    results = racing([session(f"SELECT review_reward_task('{request}',true,'');", user=ADMIN, admin=True) for request in ids])
    assert all(result.returncode == 0 for result in results), [r.stderr for r in results]
    assert balance(user) == 100 and pending(user) == 0
    return ids

# Only own authenticated submissions, valid claim amounts, actual private screenshots.
for step in (0, 4, 5, 6):
    submit(C, step, '20' if step == 0 else 'NULL', error='Tasks 1–3')
client("SELECT submit_reward_task(1,NULL,'',NULL);", user=None, error='Please log in')
client("SELECT submit_reward_task(1,NULL,'',NULL);", role='anon', error='permission denied')
client(f"SELECT submit_reward_task(1,'{D}/proof.png','',NULL);", user=C, error='own screenshot')
client(f"SELECT submit_reward_task(1,'{C}/missing.png','',NULL);", user=C, error='own screenshot')
client(f"SELECT submit_reward_task(7,'{C}/proof.png','',NULL);", user=C, error='Invalid task')
client(f"INSERT INTO task_submissions(user_id,task_id,proof_image_url) VALUES('{C}',1,'{C}/proof.png');",user=C,error='permission denied')
for table in ('reward_events','reward_submissions'):
    client(f"DELETE FROM {table};", user=C, error='permission denied')
    client(f"UPDATE {table} SET user_id='{C}';", user=C, error='permission denied')
client(f"INSERT INTO reward_events(user_id,event,available_delta,pending_delta,submission_id) VALUES('{C}','joining_bonus',100,0,gen_random_uuid());",user=C,error='permission denied')
client(f"INSERT INTO reward_submissions(user_id,step,status) VALUES('{C}',6,'approved');",user=C,error='permission denied')
client(f"SELECT check_reward_prerequisites('{C}',6);",user=C,error='permission denied')
print('PASS: prerequisites, authentication, proof ownership/existence, no direct rewards or legacy submissions')

ids = stage_one(C)
review(ids[2], error='already reviewed')
submit(C, 1, error='already submitted')
for user, kwargs in [(C, {}), (C, {'extra': {'user_metadata': {'role': 'admin'}}}), (None, {'admin': True})]:
    client(f"SELECT review_reward_task('{ids[0]}',true,'');",user=user,error='Only admins',**kwargs)
client(f"SELECT review_reward_task('{ids[0]}',true,'');",role='anon',error='permission denied')
client(f"SELECT review_reward_task('{ids[0]}',true,'');",user=C,admin=True,error='Another admin')
# First 100 really is withdrawable BEFORE a claim or Task 6 exists.
client(f"INSERT INTO withdrawals(user_id,amount,payment_method) VALUES('{C}',100,'bank');",user=C)
withdrawal = sql(f"SELECT id FROM withdrawals WHERE user_id='{C}';")
client(f"SELECT approve_withdrawal('{withdrawal}');",user=ADMIN,admin=True)
assert balance(C) == 0
for amount in ('19.99','30.01','20.001',"'NaN'","'Infinity'","'-Infinity'",'NULL'):
    submit(C, 0, amount, error='Claim an amount')
client(f"SELECT submit_reward_task(4,'{C}/proof.png','',30);",user=C,error='Only the reward claim')
claim = submit(C, 0, '30')
review(claim, False, error='Explain')
review(claim, False, 'Amount not visible; upload a clearer screenshot')
assert pending(C) == 0
review(claim, error='already reviewed')
claim = submit(C, 0, '30')
review(claim)
assert pending(C) == 30 and balance(C) == 0
submit(C, 0, '20', error='already submitted')
submit(C, 6, error='Tasks 4 and 5')
a, b = submit(C, 4), submit(C, 5)
results = racing([session(f"SELECT review_reward_task('{request}',true,'');",user=ADMIN,admin=True) for request in (a,b)])
assert all(r.returncode == 0 for r in results), [r.stderr for r in results]
assert pending(C) == 130 and balance(C) == 0
client("SELECT create_internal_transfer('USER-55555555',1);",user=C,error='Insufficient')
client(f"INSERT INTO withdrawals(user_id,amount,payment_method) VALUES('{C}',1,'bank');",user=C)
blocked_withdrawal = sql(f"SELECT id FROM withdrawals WHERE user_id='{C}' AND amount=1;")
client(f"SELECT approve_withdrawal('{blocked_withdrawal}');",user=ADMIN,admin=True,error='Insufficient')
# Unrelated deposits are separate, never prerequisites or double counted in reward release.
client(f"INSERT INTO deposits(user_id,amount,payment_method,status) VALUES('{C}',7,'Bank Transfer','pending');",user=C)
deposit = sql(f"SELECT id FROM deposits WHERE user_id='{C}';")
client(f"SELECT approve_deposit('{deposit}');",user=ADMIN,admin=True)
final = submit(C, 6)
results = racing([session(f"SELECT review_reward_task('{final}',true,'');",user=ADMIN,admin=True)]*2)
assert sum(r.returncode == 0 for r in results) == 1
assert pending(C) == 0 and balance(C) == 137
assert sql(f"SELECT sum(available_delta+pending_delta) FROM reward_events WHERE user_id='{C}';") == '230'
assert sql(f"SELECT count(*) FROM reward_events WHERE user_id='{C}';") == '4'
submit(C, 6, error='already submitted')
print('PASS: early withdrawal, claim boundaries/rejection/retry, concurrent bonuses, Pending cannot be spent, single release of 130 plus unrelated deposit')

# Lower bound, no deposits at all, final rejection and retry, independent of available balance.
stage_one(D)
claim = submit(D, 0, '20'); review(claim)
a = submit(D, 4); b = submit(D, 5); review(a); review(b)
assert pending(D) == 120
client("SELECT create_internal_transfer('USER-66666666',25);",user=D)
assert balance(D) == 75
final = submit(D, 6); review(final, False, 'Please correct the group membership evidence')
assert balance(D) == 75 and pending(D) == 120
final = submit(D, 6); review(final)
assert balance(D) == 195 and pending(D) == 0
assert sql(f"SELECT count(*) FROM deposits WHERE user_id='{D}';") == '0'
assert sql(f"SELECT sum(available_delta+pending_delta) FROM reward_events WHERE user_id='{D}';") == '220'
print('PASS: claim 20 releases 120 with no deposit; final rejection preserves Pending; transfer balance preserved')

# Concurrent submissions are single; approval/rejection race changes no more than one state.
results = racing([session(f"SELECT submit_reward_task(1,'{F}/proof.png','',NULL);",user=F)]*2)
assert sum(r.returncode == 0 for r in results) == 1
request = sql(f"SELECT id FROM reward_submissions WHERE user_id='{F}';")
results = racing([session(f"SELECT review_reward_task('{request}',{decision},'Reviewed');",user=ADMIN,admin=True) for decision in ('true','false')])
assert sum(r.returncode == 0 for r in results) == 1
assert balance(F) == 0 and pending(F) == 0

assert client(f"SELECT count(*) FROM reward_events WHERE user_id='{C}';",user=D).splitlines()[-1] == '0'
assert client(f"SELECT count(*) FROM reward_submissions WHERE user_id='{C}';",user=D).splitlines()[-1] == '0'
client('SELECT * FROM reward_events;',role='anon',error='permission denied')
assert client("SELECT count(*) FROM storage.objects WHERE bucket_id='reward-proofs';",user=C).splitlines()[-1] == '1'
assert client("SELECT count(*) FROM storage.objects WHERE bucket_id='reward-proofs';",user=ADMIN,admin=True).splitlines()[-1] == '4'
assert client("SELECT count(*) FROM storage.objects WHERE bucket_id='reward-proofs';",role='anon').splitlines()[-1] == '0'
# Even a permissive update/delete policy cannot mutate submitted proof.
sql("CREATE POLICY synthetic_broad_update ON storage.objects FOR UPDATE TO authenticated USING(true) WITH CHECK(true); CREATE POLICY synthetic_broad_delete ON storage.objects FOR DELETE TO authenticated USING(true);")
client(f"UPDATE storage.objects SET name='{C}/changed.png' WHERE name='{C}/proof.png';",user=C)
client("DELETE FROM storage.objects WHERE bucket_id='reward-proofs';",user=C)
assert sql("SELECT count(*) FROM storage.objects WHERE bucket_id='reward-proofs';") == '4'
assert sql(f"SELECT count(*) FROM storage.objects WHERE name='{C}/proof.png';") == '1'
client(f"INSERT INTO storage.objects(bucket_id,name) VALUES('reward-proofs','{D}/foreign.png');",user=C,error='row-level security')
# Reapplication preserves events/balances, signup still creates the legacy-compatible profile.
sql(migration)
assert balance(C) == 137 and balance(D) == 195 and pending(C) == 0
assert base.balance() == legacy_balance
assert sql('SELECT count(*) FROM task_submissions;') == legacy_submissions
assert sql(f"SELECT count(*) FROM profiles WHERE id IN ('{C}','{D}','{E}','{F}');") == '4'
print('PASS: concurrent submissions/review race, RLS isolation, private immutable proofs, reapplication and legacy/signup preservation')
