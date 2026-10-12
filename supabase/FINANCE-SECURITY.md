# Finance security fixes

## Findings from the supplied database report

- Approval functions tested `role <> 'admin'`. A missing role yields SQL NULL and
  does not enter the rejection branch. The functions were executable by anonymous
  and authenticated API roles.
- Task/withdrawal insertion checked ownership but allowed client-supplied status.
- Only admins could insert deposits; the client's deposit form needed its own
  pending-only policy.
- Internal transfer rows could be inserted directly, without the transfer RPC's
  debit/credit operation. Recipients could not read incoming transfer records.
- Proof screenshot reads were allowed for every authenticated user.
- Multiple submissions of the same task could each be approved and rewarded.
- Numeric payment amounts had no positive/finite constraints. Negative withdrawals
  could increase balances when approved. Transfers also accepted special numeric
  values and risked deadlocks when executed in opposite directions.

Broad table grants alone do not establish a bypass: row-level security also applies.
The tests below reproduce the missing-role approval and approved-status insertion
issues against a reconstruction of the supplied schema, using synthetic accounts.

## Deployment order

1. Back up the hosted database. Run
   `migrations/202610120001_finance_security.sql` in Supabase SQL Editor as the
   database owner. It is transactional and can be reapplied. If it fails, retain
   the error and resolve it before publishing the matching frontend.
2. Publish the frontend change in the same update. Admin rejection buttons now use
   `reject_deposit`, `reject_withdrawal`, and `reject_task_submission` RPCs. Old
   frontend rejection buttons cannot directly update rows after this migration.
3. Test with dedicated client and admin accounts, using sample amounts only:
   request deposit → approve once; request withdrawal → approve once; reject new
   requests; retry rejected task proof; verify balances and both sides of transfers.
   Check actual provider receipts separately before approving real deposits/payouts.
4. Export the updated launch-readiness report for hosted configuration review.

The migration restricts browser writes, including column grants; admins approve or
reject via RPCs. Browser roles cannot create objects in the public schema. The
existing reference lookup is used internally, with browser execution revoked.
Its source was omitted from the first report; the revised diagnostic includes it.
The local test adapter verifies transfer accounting, not that production helper's
recipient-matching behavior.

Task proofs become a private bucket. Existing public image links will no longer
work; authenticated owners/admins need storage downloads or signed URLs. The
current admin UI displays proof text; a signed screenshot viewer is still needed.

Payment inputs use the existing forms' two-decimal precision. No currency is chosen
by this migration. New payments must be positive finite amounts; task rewards may
be zero. Invalid historical rows are preserved and can be rejected, but cannot be approved.
Rejected records are exempt from the amount constraint so their original amounts
can be retained without affecting balances. New/updated
balances cannot be negative or non-finite. No historical balances are recalculated;
previous approval bypasses or duplicate rewards require a separate account audit.

Withdrawal approval deducts the balance once. Pending requests do not reserve funds;
competing requests are checked against the locked current balance at approval.
Database approval records a decision; it does not send money through a bank/mobile
money provider. Task approval still follows the existing immediate-credit behavior.
Pending rewards, joining bonuses, and Task 6 unlocking are NOT implemented here.
Only Task 1 exists in the supplied task catalog. Reward amounts and unlock rules
must be confirmed before implementing that separate change.

## Local tests

Use a disposable PostgreSQL 17 container. The test drops and recreates only
`finance_security_test` inside that container. Never point it at production.

```sh
docker run --rm -d --name john-lian-finance-test --network none -e POSTGRES_HOST_AUTH_METHOD=trust postgres:17
until docker exec john-lian-finance-test pg_isready -h 127.0.0.1 -U postgres; do sleep 1; done
python3 supabase/tests/test_finance_security.py
docker stop john-lian-finance-test
```

The runner honors `DOCKER_HOST`, `DOCKER_CONTEXT`, and `FINANCE_TEST_CONTAINER`.
It covers legacy reproduction, absent/forged roles, client ownership/status rules,
invalid amounts, single credit/debit, rejected requests, duplicate task rewards,
concurrent approvals and withdrawals, reciprocal transfers, approval/rejection
races, account isolation, proof privacy, and repeat migration.

Live Supabase JWT/PostgREST integration, storage signed downloads, the production
reference helper, actual payout providers, and full Task 6 flows remain unverified.
