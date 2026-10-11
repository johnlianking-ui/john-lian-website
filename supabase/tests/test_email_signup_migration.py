"""Only for the task-owned, disposable PostgreSQL Docker container."""
import os
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[2]
container = os.environ.get('EMAIL_SIGNUP_TEST_CONTAINER', 'john-lian-signup-test')
# Docker's standard DOCKER_HOST/DOCKER_CONTEXT variables select the daemon.
base = ['docker', 'exec', '-i', container]
subprocess.run(base + ['dropdb', '-U', 'postgres', '--if-exists', 'email_signup_test'], check=True)
subprocess.run(base + ['createdb', '-U', 'postgres', 'email_signup_test'], check=True)
fixture = """
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN CREATE ROLE anon NOLOGIN; END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF;
END $$;
CREATE SCHEMA auth;
CREATE TABLE auth.users(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), email text, email_confirmed_at timestamptz, raw_user_meta_data jsonb DEFAULT '{}');
CREATE TABLE public.profiles(id uuid PRIMARY KEY REFERENCES auth.users(id), invitation_code text NOT NULL UNIQUE, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE public.referrals(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), invited_user_id uuid UNIQUE, inviter_user_id uuid, invitation_code text);
CREATE FUNCTION public.generate_invitation_code() RETURNS text LANGUAGE sql AS $$ SELECT upper(replace(gen_random_uuid()::text,'-','')) $$;
INSERT INTO auth.users(email) VALUES ('existing@example.invalid');
INSERT INTO profiles(id,invitation_code) SELECT id,'EXISTING' FROM auth.users;
CREATE FUNCTION public.handle_new_user() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Invalid invitation code.'; END; $$;
CREATE TRIGGER on_auth_user_created AFTER INSERT ON auth.users FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();
"""
migration = (root / 'supabase/migrations/202610110001_email_verification_signup.sql').read_text()
checks = """
INSERT INTO auth.users(email) VALUES ('email-only@example.invalid');
INSERT INTO auth.users(email,raw_user_meta_data) VALUES ('metadata@example.invalid','{"invitation_code":"INVALID", "email_verified":true}');
DO $$ BEGIN
 IF (SELECT count(*) FROM profiles) <> 3 THEN RAISE EXCEPTION 'Missing profiles'; END IF;
 IF EXISTS(SELECT 1 FROM referrals) THEN RAISE EXCEPTION 'Unexpected referral'; END IF;
 IF NOT EXISTS(SELECT 1 FROM profiles WHERE invitation_code='EXISTING') THEN RAISE EXCEPTION 'Existing profile changed'; END IF;
 IF EXISTS(SELECT 1 FROM auth.users WHERE email_confirmed_at IS NOT NULL) THEN RAISE EXCEPTION 'Premature confirmation'; END IF;
 IF has_function_privilege('authenticated','public.handle_new_user()','EXECUTE') THEN RAISE EXCEPTION 'Trigger callable by browser'; END IF;
END $$;
"""
subprocess.run(base + ['psql','-U','postgres','-d','email_signup_test','-v','ON_ERROR_STOP=1'], input=fixture + migration + checks + migration, text=True, check=True, stdout=subprocess.DEVNULL)
print('PASS: email-only signup, profile creation, no referrals, existing profile preservation, unverified state, restricted trigger and repeat migration')
