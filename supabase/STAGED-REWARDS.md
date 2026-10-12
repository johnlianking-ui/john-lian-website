# Six-task rewards (USD is provisional)

This replaces new submissions to the old per-task system. Existing balances, old submissions and signup profiles are preserved; no historical task is automatically awarded a new bonus.

## Rules

| Approval | Available balance change | Pending change |
| --- | ---: | ---: |
| All three screenshots for Tasks 1–3 | +100 | 0 |
| Screenshot verifying a claimed amount of 20–30 | 0 | +20–30 |
| Both membership screenshots for Tasks 4–5 | 0 | +100 |
| Task 6 final review of all approved evidence | +120–130 | −120–130 |

Total rewards: 220–230 per completed participant. Task 6 pays no extra bonus. **There is no payment, deposit or fee to unlock rewards.** The first 100 can be withdrawn or transferred before Task 6. An ordinary deposit stays separate and does not count toward eligibility. Available balances include earlier activity; Program Rewards counts only the new program and includes Pending rewards before spending.

Group links and reading instructions are shared separately by the operator. Task 6 is an admin's final review of approved evidence, requested by the participant without another screenshot. A rejection must explain what needs correcting; clients can submit a new request. Approved evidence and amounts cannot be edited by the browser.

## Rollout

1. Save a database backup using your existing Supabase backup process. Review the provisional USD amounts and ensure advertiser funding covers rewards before inviting real participants. Current bank/mobile-money instructions remain samples; these changes do not configure a real payout provider.
2. In **Supabase → SQL Editor → New query**, run `202610120001_finance_security.sql`, then `202610120002_staged_rewards.sql`, in that order. The generated `setup-rewards.sql` contains both. This is required even if the first migration was applied previously. Do not subsequently reapply the first migration alone: it would reopen the old submission grants.
3. Publish the matching website files (`index.html`, `style.css`, `rewards.js`) together. Before the database update, the new UI will show a rewards-unavailable error rather than use the old reward rules.
4. Refresh the deployed site. Log in with a test member and a separate admin. Admin privilege must be in trusted `app_metadata.role = "admin"`; do not put it in user-editable metadata. An admin cannot review their own new-program submissions.
5. Complete the acceptance checks below with controlled test accounts before inviting participants. These steps affect real balances if run in production; use a staging Supabase project where available.

The agent has no Supabase management connection. The SQL has been tested locally; it has **not** been applied to the hosted project by the agent.

## Acceptance checks

- Upload one PNG/JPEG/WebP screenshot (maximum 5 MB) for each of Tasks 1–3. Approve them from the admin reward review cards, checking the private screenshots. Only the third approved task credits 100.
- Withdraw that 100 through the existing request/admin approval flow before Task 6. Approval debits the available balance; payout delivery still requires the operator's actual payment process. Pending withdrawals do not reserve balance.
- Submit a claim of 20 or 30 with its screenshot; reject once with a reason, then retry and approve. Only approved amounts become Pending. Values outside 20–30 or with more than two decimal places are rejected.
- Approve Tasks 4–5. Pending should be 120 or 130. This amount cannot fund a withdrawal or internal transfer yet.
- Request Task 6. Admin opens earlier approved evidence and verifies it, then approves the release. Pending becomes 0 and available increases by exactly 120 or 130. A repeated review must fail without paying again. No deposit is required.
- Check both sides of an internal transfer and the transaction history. The release moves Pending to Available; it does not increase total Program Rewards again.
- Use Refresh tasks and balances / Refresh reward reviews to see remote approvals. Opening history fetches current transactions. History shows the latest 100 entries per category; new program reward history is separate from legacy task records whose historical payout amounts were not recorded.
- Verify registration/email delivery and login against your hosted Supabase setup. These integrations were not changed by this implementation.

## Accounting and access

`reward_submissions` holds steps 1–6 and step 0 (the separate claim). Only `submit_reward_task` can create browser requests. Each user can have one pending/approved submission per step; rejected attempts remain in history. `review_reward_task` is restricted to authenticated admins and serializes stage changes per user.

`reward_events` is an immutable browser-readable ledger. Unique `(user_id, event)` prevents repeated stage credits. Available money is also credited to the existing `account_balances` in the same transaction. Pending is derived from the ledger and is never included in spendable funds. The existing secure withdrawal/transfer functions remain authoritative.

`reward-proofs` is a separate private bucket. Clients can upload/read only their own paths; admins can view signed screenshots. Browser update/delete is blocked, including through other permissive storage policies. Uploaded objects whose submission failed may remain unreferenced; do not delete referenced evidence. Signup/referral behavior is unchanged (no shareable invitation codes).

## Local verification

Requires Docker, Python 3 and an existing `postgres:17` image. Honor `DOCKER_HOST` / `DOCKER_CONTEXT` if configured.

```sh
docker run --rm -d --name john-lian-rewards-test --network none -e POSTGRES_HOST_AUTH_METHOD=trust postgres:17
until docker exec john-lian-rewards-test pg_isready -h 127.0.0.1 -U postgres; do sleep 1; done
FINANCE_TEST_CONTAINER=john-lian-rewards-test python3 supabase/tests/test_staged_rewards.py
docker stop john-lian-rewards-test
```

The runner resets only `finance_security_test` in that disposable container. It runs legacy finance regressions first, then new reward tests with synthetic SQL auth and storage adapters. It does not emulate GoTrue, real JWT issuance, PostgREST, Storage upload transport, or payouts. The legacy recipient-reference helper is a synthetic adapter because its production source was absent from the supplied report.

For UI checks, run `python3 -m http.server 3000 --bind 0.0.0.0` from this repository, register Preview, and open `http://localhost:3000` using `coderabbit-agent-browser`. Then run `python3 tests/test_rewards_browser.py`. It uses synthetic SDK responses in the shared Chromium browser at desktop/mobile widths; it sends no real financial requests.
