-- Run in Supabase SQL Editor as database owner BEFORE publishing the new signup UI.
-- Existing profile codes/referral records are preserved for compatibility, but
-- registration no longer requires a referral code or creates a referral.
BEGIN;
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
  INSERT INTO public.profiles (id, invitation_code)
  VALUES (NEW.id, public.generate_invitation_code());
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.handle_new_user() FROM PUBLIC, anon, authenticated;
COMMIT;
