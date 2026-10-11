# Email verification signup

The selected flow is email → emailed one-time code → password. Referral codes
and three-person sharing have been removed from this implementation.

## Required Supabase setup (before publishing the website)

1. Back up the database and run `migrations/202610110001_email_verification_signup.sql`
   in Supabase SQL Editor as database owner. The existing `on_auth_user_created`
   trigger calls `handle_new_user`; this migration removes its invitation-code
   requirement while retaining profile creation and existing records.
   Do not run the earlier invitation-limit proposal: it was local only and superseded.
2. Enable the Email provider and allow new signups in Supabase Authentication.
   Keep email confirmation enabled.
3. In Authentication email templates, configure BOTH **Confirm signup** and
   **Magic Link** to display the OTP using `{{ .Token }}`. Example HTML:

   ```html
   <h2>Your John Lian verification code</h2>
   <p>Enter this code on the website:</p>
   <p><strong>{{ .Token }}</strong></p>
   <p>If you did not request this code, ignore this email. Do not share the code.</p>
   ```

   New and returning users may receive different templates. A confirmation link
   alone does not supply the code required by this form.
4. Configure custom SMTP with a verified sender for delivery to clients. Supabase's
   built-in test mail service has recipient/rate restrictions; check the project's
   current delivery configuration. Store SMTP credentials only in Supabase settings.
5. Configure token length/expiry and email send limits in Supabase Auth. The UI
   accepts 6–10 numeric digits and provides a 60-second resend countdown; Supabase
   enforces the actual expiry, one-time use and request limits.
6. Publish the frontend only after steps 1–5. Test delivery, invalid/expired/reused
   codes, password setup and subsequent password login with a dedicated test inbox.

No separate email worker or referral email queue is required. Emails are sent by
Supabase Auth through its configured SMTP provider. Email requests do not prove
inbox delivery. Real email delivery has not been tested in this workspace.

## Existing accounts

An email OTP proves control of the account's email and signs the user in. The form
explicitly explains that saving a password replaces the password for an existing
account. The verified identity is rechecked before saving. Verification is handled
by Supabase; no valid code or server-side email credential is stored in the browser.

## Tests

Use a disposable PostgreSQL container, never production. The test deletes and
recreates the `email_signup_test` database inside the selected container.

```bash
docker run --rm -d --name john-lian-signup-test --network none -e POSTGRES_HOST_AUTH_METHOD=trust postgres:17
# Wait until this reports "accepting connections":
docker exec john-lian-signup-test pg_isready -U postgres
python3 supabase/tests/test_email_signup_migration.py
docker stop john-lian-signup-test
```

The script creates the minimal `anon` and `authenticated` roles itself. It uses
Docker's standard `DOCKER_HOST`/`DOCKER_CONTEXT` configuration. To use a different
disposable container, set `EMAIL_SIGNUP_TEST_CONTAINER` to its name.
