"""Destructive ONLY within finance_security_test on a disposable PostgreSQL container.

Use Docker's DOCKER_HOST/DOCKER_CONTEXT; set FINANCE_TEST_CONTAINER if needed.
No real Supabase users, emails, balances, or payment providers are contacted.
"""
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

ROOT = Path(__file__).resolve().parents[2]
CONTAINER = os.environ.get('FINANCE_TEST_CONTAINER', 'john-lian-finance-test')
DOCKER = ['docker', 'exec', '-i', CONTAINER]
PSQL = DOCKER + ['psql', '-X', '-U', 'postgres', '-d', 'finance_security_test', '-qAt', '-v', 'ON_ERROR_STOP=1']
A = '11111111-1111-4111-8111-111111111111'
B = '22222222-2222-4222-8222-222222222222'
ADMIN = '99999999-9999-4999-8999-999999999999'


def sql(source, error=None):
    result = subprocess.run(PSQL, input=source, text=True, capture_output=True)
    if error is None:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0 and error in result.stderr, (error, result.stdout, result.stderr)
    return result.stdout.strip()


def session(source, user=A, admin=False, role='authenticated', extra=None):
    claims = {'sub': user} if user else {}
    if admin:
        claims['app_metadata'] = {'role': 'admin'}
    if extra:
        claims.update(extra)
    encoded = json.dumps(claims).replace("'", "''")
    return f"BEGIN; SET LOCAL ROLE {role}; SELECT set_config('request.jwt.claims','{encoded}',true);\n{source}\nCOMMIT;"


def client(source, **kwargs):
    error = kwargs.pop('error', None)
    return sql(session(source, **kwargs), error)


def balance(user=A):
    return sql(f"SELECT balance FROM public.account_balances WHERE user_id='{user}';")


def racing(sources):
    barrier = Barrier(len(sources))
    def run(source):
        barrier.wait()
        return subprocess.run(PSQL, input=source, text=True, capture_output=True)
    with ThreadPoolExecutor(max_workers=len(sources)) as executor:
        return list(executor.map(run, sources))


subprocess.run(DOCKER + ['dropdb', '-U', 'postgres', '--if-exists', 'finance_security_test'], check=True)
subprocess.run(DOCKER + ['createdb', '-U', 'postgres', 'finance_security_test'], check=True)
sql("""DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='anon') THEN CREATE ROLE anon NOLOGIN; END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF;
END $$;""")
sql((ROOT / 'supabase/tests/fixtures/legacy-finance.sql').read_text())
sql(f"""
INSERT INTO auth.users(id,email) VALUES('{A}','a@example.invalid'),('{B}','b@example.invalid'),('{ADMIN}','admin@example.invalid');
INSERT INTO public."Tasks"(id,title,description,reward,status) VALUES(1,'Task 1','Synthetic',1,'active'),(2,'Task 2','Synthetic',2,'active');
INSERT INTO public.account_balances(user_id,balance) VALUES('{A}',100),('{B}',100);
INSERT INTO public.deposits(id,user_id,amount,payment_method) VALUES('10000000-0000-4000-8000-000000000001','{A}',25,'Bank Transfer');
INSERT INTO public.withdrawals(id,user_id,amount,payment_method) VALUES('20000000-0000-4000-8000-000000000009','{A}',-5,'bank');
INSERT INTO storage.buckets(id,public) VALUES('task-proofs',true);
INSERT INTO storage.objects(bucket_id,name) VALUES('task-proofs','{A}/proof.png'),('task-proofs','{B}/proof.png');
""")
# Reproduce two reported flaws locally, then roll back every baseline mutation.
baseline = session("SELECT public.approve_deposit('10000000-0000-4000-8000-000000000001');").replace('COMMIT;', 'ROLLBACK;')
sql(baseline)
sql(session(f"INSERT INTO public.task_submissions(user_id,task_id,status) VALUES('{A}',1,'approved');").replace('COMMIT;', 'ROLLBACK;'))
assert balance() == '100'
print('PASS: reproduced legacy approval bypass and client-approved submission; baseline changes rolled back')

migration = (ROOT / 'supabase/migrations/202610120001_finance_security.sql').read_text()
sql(migration)
sql(migration)  # repeatable
assert balance() == '100'
sql("INSERT INTO auth.users(id,email) VALUES('33333333-3333-4333-8333-333333333333','new@example.invalid');")
assert sql("SELECT count(*) FROM profiles WHERE id='33333333-3333-4333-8333-333333333333';") == '1'
assert sql("SELECT amount FROM withdrawals WHERE id='20000000-0000-4000-8000-000000000009';") == '-5'

# The admin role must be present in trusted app_metadata and require a user ID.
for fn, arg in [('approve_deposit', "'10000000-0000-4000-8000-000000000001'"),
                ('approve_withdrawal', "'20000000-0000-4000-8000-000000000009'"),
                ('approve_task_submission', '1'), ('reject_deposit', "gen_random_uuid()"),
                ('reject_withdrawal', "gen_random_uuid()"), ('reject_task_submission', '1')]:
    call = f'SELECT public.{fn}({arg});'
    client(call, error='Only admins')
    client(call, extra={'user_metadata': {'role': 'admin'}}, error='Only admins')
    client(call, user=None, admin=True, error='Only admins')
    client(call, role='anon', error='permission denied')
print('PASS: absent role, user-editable role, absent user ID and anonymous approval/rejection blocked')

# Clients cannot directly change balances, approve requests, or forge transfers.
for command in [f"UPDATE account_balances SET balance=999 WHERE user_id='{A}';",
                f"INSERT INTO account_balances(user_id,balance) VALUES('{ADMIN}',999);",
                "UPDATE deposits SET status='approved';", "UPDATE withdrawals SET status='approved';",
                "UPDATE task_submissions SET status='approved';",
                f"INSERT INTO internal_transfers(sender_id,recipient_id,recipient_reference,amount,status) VALUES('{A}','{B}','USER-22222222',10,'completed');",
                f"INSERT INTO referrals(invited_user_id,inviter_user_id,invitation_code) VALUES('{A}','{B}','OLD');"]:
    client(command, error='permission denied')
client("UPDATE deposits SET status='approved';", user=ADMIN, admin=True, error='permission denied')
client(f"INSERT INTO deposits(user_id,amount,payment_method,status) VALUES('{B}',1,'Bank Transfer','pending');", error='row-level security')
client(f"INSERT INTO deposits(user_id,amount,payment_method,status) VALUES('{A}',1,'Bank Transfer','approved');", error='row-level security')
client(f"INSERT INTO task_submissions(user_id,task_id,status,proof_image_url) VALUES('{A}',1,'approved','{A}/proof.png');", error='row-level security')
client(f"INSERT INTO task_submissions(user_id,task_id,status,proof_image_url) VALUES('{A}',1,'pending','{B}/proof.png');", error='row-level security')
client(f"INSERT INTO task_submissions(user_id,task_id,status,proof_image_url) VALUES('{A}',999,'pending','{A}/proof.png');", error='row-level security')
client(f"INSERT INTO task_submissions(user_id,task_id,status,reviewed_at) VALUES('{A}',1,'pending',now());", error='permission denied')
for amount in ['0','-1',"'NaN'", "'Infinity'", "'-Infinity'", '1.001']:
    for table, method in [('deposits','Bank Transfer'),('withdrawals','bank')]:
        client(f"INSERT INTO {table}(user_id,amount,payment_method) VALUES('{A}',{amount},'{method}');", error='valid_payment_amount')
    client(f"SELECT create_internal_transfer('USER-22222222',{amount});", error='Invalid transfer amount')
client("SELECT create_internal_transfer('USER-22222222',NULL);", error='Invalid transfer amount')
client(f"INSERT INTO deposits(user_id,amount,payment_method,status) VALUES('{A}',5,'Mobile Money','pending');")
client(f"INSERT INTO withdrawals(user_id,amount,payment_method) VALUES('{A}',5,'bank');")
client(f"INSERT INTO task_submissions(user_id,task_id,proof_text,proof_image_url,status) VALUES('{A}',1,'Synthetic','{A}/proof.png','pending');")
assert balance() == '100'
print('PASS: pending-only own requests, column restrictions, finite positive amounts, immutable balances and transfers')

client("SELECT approve_deposit('10000000-0000-4000-8000-000000000001');", user=ADMIN, admin=True)
assert balance() == '125'
client("SELECT approve_deposit('10000000-0000-4000-8000-000000000001');", user=ADMIN, admin=True, error='already been processed')
client("SELECT reject_deposit('10000000-0000-4000-8000-000000000001');", user=ADMIN, admin=True, error='already processed')
client("SELECT approve_withdrawal('20000000-0000-4000-8000-000000000009');", user=ADMIN, admin=True, error='Invalid withdrawal amount')
client("SELECT reject_withdrawal('20000000-0000-4000-8000-000000000009');", user=ADMIN, admin=True)
assert balance() == '125'
withdrawal = sql("SELECT id FROM withdrawals WHERE amount=5;")
client(f"SELECT reject_withdrawal('{withdrawal}');", user=ADMIN, admin=True)
client(f"SELECT approve_withdrawal('{withdrawal}');", user=ADMIN, admin=True, error='already been processed')
deposit = sql("SELECT id FROM deposits WHERE amount=5;")
client(f"SELECT reject_deposit('{deposit}');", user=ADMIN, admin=True)
client(f"SELECT approve_deposit('{deposit}');", user=ADMIN, admin=True, error='already been processed')
submission = sql("SELECT id FROM task_submissions WHERE status='pending';")
client(f"SELECT reject_task_submission({submission});", user=ADMIN, admin=True)
client(f"SELECT approve_task_submission({submission});", user=ADMIN, admin=True, error='already been processed')
assert balance() == '125'
# Retry after rejection is allowed, and only one task reward can ever be approved.
client(f"INSERT INTO task_submissions(user_id,task_id,proof_image_url,status) VALUES('{A}',1,'{A}/retry.png','pending');")
submission = sql("SELECT id FROM task_submissions WHERE status='pending';")
client(f"SELECT approve_task_submission({submission});", user=ADMIN, admin=True)
assert balance() == '126'
client(f"SELECT approve_task_submission({submission});", user=ADMIN, admin=True, error='already been processed')
print('PASS: approval applies exactly once; rejection changes no money; rejected requests cannot be approved')

# Concurrent retries/requests must preserve balances, statuses, and single-task credit.
sql(f"INSERT INTO deposits(id,user_id,amount,payment_method) VALUES('10000000-0000-4000-8000-000000000003','{A}',7,'Bank Transfer');")
results = racing([session("SELECT approve_deposit('10000000-0000-4000-8000-000000000003');", user=ADMIN, admin=True)]*2)
assert sum(r.returncode == 0 for r in results) == 1
assert balance() == '133'
sql(f"INSERT INTO task_submissions(id,user_id,task_id,status) VALUES(100,'{A}',2,'pending'),(101,'{A}',2,'pending');")
results = racing([session(f'SELECT approve_task_submission({sid});', user=ADMIN, admin=True) for sid in (100,101)])
assert sum(r.returncode == 0 for r in results) == 1
assert balance() == '135'
sql(f"INSERT INTO withdrawals(id,user_id,amount,payment_method) VALUES('20000000-0000-4000-8000-000000000001','{A}',80,'bank'),('20000000-0000-4000-8000-000000000002','{A}',80,'bank');")
results = racing([session(f"SELECT approve_withdrawal('20000000-0000-4000-8000-00000000000{i}');", user=ADMIN, admin=True) for i in (1,2)])
assert sum(r.returncode == 0 for r in results) == 1
assert balance() == '55'
client("SELECT create_internal_transfer('USER-11111111',1);", error='yourself')
client("SELECT create_internal_transfer('USER-MISSING',1);", error='Recipient not found')
client("SELECT create_internal_transfer('USER-22222222',9999);", error='Insufficient')
client("SELECT create_internal_transfer('USER-22222222',5);")
assert balance() == '50' and balance(B) == '105'
results = racing([session("SELECT create_internal_transfer('USER-22222222',1);", user=A),session("SELECT create_internal_transfer('USER-11111111',1);", user=B)])
assert all(r.returncode == 0 for r in results), [r.stderr for r in results]
assert balance() == '50' and balance(B) == '105'
print('PASS: concurrent deposit/task approvals credit once, competing withdrawals cannot overdraw, reciprocal transfers conserve balances')

# Approval versus rejection: one wins; balance must match the winning status.
sql(f"INSERT INTO deposits(id,user_id,amount,payment_method) VALUES('10000000-0000-4000-8000-000000000004','{A}',3,'Bank Transfer');")
results = racing([session(f"SELECT {action}_deposit('10000000-0000-4000-8000-000000000004');",user=ADMIN,admin=True) for action in ('approve','reject')])
assert sum(r.returncode == 0 for r in results) == 1
approved = sql("SELECT status FROM deposits WHERE id='10000000-0000-4000-8000-000000000004';") == 'approved'
assert balance() == ('53' if approved else '50')

# RLS isolates accounts, allows both transfer parties, and keeps proofs private.
assert client(f"SELECT count(*) FROM account_balances WHERE user_id='{B}';").splitlines()[-1] == '0'
assert client(f"SELECT count(*) FROM internal_transfers WHERE recipient_id='{B}';",user=B).splitlines()[-1] == '2'
assert client("SELECT count(*) FROM storage.objects;").splitlines()[-1] == '1'
assert client("SELECT count(*) FROM storage.objects;",user=ADMIN,admin=True).splitlines()[-1] == '2'
assert client("SELECT count(*) FROM storage.objects;",role='anon').splitlines()[-1] == '0'
assert sql("SELECT public FROM storage.buckets WHERE id='task-proofs';") == 'f'
client("SELECT find_user_by_reference('USER-22222222');",error='permission denied')
sql(migration)
assert balance() == ('53' if approved else '50')
print('PASS: approval/rejection race, cross-account isolation, recipient history, private proof access and migration reapplication')

report = json.loads(sql((ROOT / 'supabase/diagnostics/launch-readiness.sql').read_text()))
assert any(f['name'].startswith('find_user_by_reference(') for f in report['functions'])
assert len(report['tasks']) == 2
print('PASS: revised diagnostic includes reference helper without reading customer rows')
