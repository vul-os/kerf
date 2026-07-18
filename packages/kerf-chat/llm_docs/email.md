# Transactional email (retired)

Kerf sends no email anywhere. There is no `/admin/email` page, no
`cloud_email_log`, no `cloud_email_credentials`, no welcome/receipt/
low-balance notifications — none of it exists any more (decisions.md's
2026-07-17 "Addendum: local git only; no OAuth; accounts shrink to the
box" ADR: "Transactional email is retired with the accounts it served").

## What to tell a user who asks about email

If a user asks "did I get a receipt," "why didn't the welcome email
arrive," or anything else about account email, the answer is simply:
kerf never sends email. Accounts on a single-user local install need no
verification at all; accounts on a shared multi-user node are created
directly by the operator (`kerf admin` commands), not by an email flow.
Password recovery is local-account recovery (`kerf admin reset-password
<email>`) delivered out of band by the operator, not by email.

There is no admin UI, log table, or LLM tool surface for this topic —
don't point a user at `/admin/email`, it doesn't exist.
