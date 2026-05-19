# Rate limiting

Kerf enforces rate limits on a small number of high-traffic endpoints to protect the service from abuse and keep performance consistent for all users. Most normal usage is well within the limits. This page explains what can trigger a rate-limit response and how to handle it.

---

## What triggers rate limiting

Five categories of requests are gated:

| Action | Limit | Window |
|---|---|---|
| Sign-in attempts | 10 per IP | 60 seconds |
| Account registration | 5 per IP | 1 hour |
| Sending a message to the AI assistant | 30 per user | 60 seconds |
| Uploading photos to a file | 60 per user | 60 seconds |
| Pushing to a connected GitHub/GitLab repo | 10 per project | 60 seconds |

All other endpoints — opening projects, editing files, browsing the library, making commits, running the commit graph — are not rate-limited.

---

## What a rate-limited response looks like

When a limit is exceeded, Kerf returns `HTTP 429 Too Many Requests`. In the app, this appears as a toast notification:

> **Too many requests — try again in N seconds**

where N is the number of seconds until the rate-limit window resets. The toast includes the countdown so you know exactly when to retry.

If you are working with the API directly:

```
HTTP/1.1 429 Too Many Requests
Retry-After: 42

{
  "detail": "rate limit exceeded",
  "retry_after": 42
}
```

The `retry_after` value in the JSON body and the `Retry-After` header are the same integer.

---

## How to back off

**In the app:** wait for the toast countdown, then retry. There is no need to reload the page.

**In scripts or integrations:**

1. Check the HTTP status code. On 429, read `retry_after` from the JSON body.
2. Sleep for `retry_after + 1` seconds (the extra second avoids a clock-skew retry).
3. Retry the request.

Example (Python):

```python
import time, requests

def call_with_backoff(session, url, **kwargs):
    while True:
        r = session.post(url, **kwargs)
        if r.status_code == 429:
            wait = r.json().get("retry_after", 10) + 1
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r
```

---

## Usage examples

### You hit the sign-in limit

If you are testing authentication or an automation script is cycling credentials, you may see a 429 on `/auth/login`. Wait 60 seconds and try again. If this is happening in normal usage, check that your password manager or SSO integration is not sending repeated login attempts.

### You are sending many AI messages quickly

The 30-messages-per-minute limit is generous for interactive use. If you are running an automated loop that sends messages programmatically, add a `sleep(2)` between requests to stay within the window.

### A CI pipeline is pushing frequently

`git push` to Kerf is limited to 10 pushes per project per 60 seconds. A normal development workflow — one push per feature branch, a few times a day — will never approach this. If your CI is pushing on every commit at high frequency, add `sleep` between push steps or batch your commits before pushing.

---

## Common questions

### Will rate limiting interrupt an in-progress AI conversation?

No. The 30-message limit applies to new messages sent to the assistant. An ongoing response that is already streaming is not interrupted.

### Are rate limits per user or per IP?

It depends on the endpoint. Sign-in and registration are keyed by IP address (so a shared NAT can reduce the effective limit). Message sending and photo uploads are keyed by user ID. Git push is keyed by project ID.

### Can the limits be raised?

For cloud accounts, limits are fixed. If you are self-hosting Kerf, the limits are configured in the source and can be adjusted by modifying the rate-limit dependency in `kerf_core/dependencies.py`. See [local-self-host.md](/docs/local-self-host) for self-hosting notes.

### Is there a way to see my current usage before hitting the limit?

Not yet — no usage-counter endpoint is exposed in the current release.

---

## Related pages

- [account-and-auth.md](/docs/account-and-auth) — sign-in and authentication
- [github-sync.md](/docs/github-sync) — push/pull to GitHub and GitLab
- [local-self-host.md](/docs/local-self-host) — self-hosting and configuration
