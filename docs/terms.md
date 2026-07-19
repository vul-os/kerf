# Terms of Service

**Effective date:** 2026-05-15

These terms govern your use of the **hosted Kerf service at `kerf.sh`**
(the "Service"). If you run Kerf locally from the open-source code, the
[MIT License](https://github.com/vul-os/kerf/blob/main/LICENSE) applies
to that copy and these terms do not.

By creating an account or using the Service, you agree to these terms.

## 1. The Service

Kerf provides a chat-driven CAD platform — mechanical, electronics,
drawings, BIM — running on our infrastructure. Kerf is 100% MIT-licensed
and available at [github.com/vul-os/kerf](https://github.com/vul-os/kerf).
`kerf.sh` runs byte-identical software to what you can self-host; using it
here is a convenience (rented uptime), not a paid subscription — Kerf has
no paid product and charges nothing for storage, LLM usage, or compute.

## 2. Accounts

- You must be 16 or older to create an account.
- You're responsible for keeping your password and API tokens secret. If
  a token is compromised, rotate it immediately from your Profile page.
- One person, one account. Workspaces are for teams; team members each
  have their own account.

## 3. Acceptable use

You agree not to use the Service to:

- Violate any law or regulation, or another person's rights.
- Upload malware, exploit code targeting other users, or content
  designed to defraud.
- Send unsolicited bulk messages, spam, or phishing through any Kerf
  feature.
- Scrape, mirror, or resell the Service's content without our written
  consent (your own projects are yours to export, of course — see
  Section 5).
- Reverse-engineer or stress-test our infrastructure beyond ordinary use.
  If you want to run a load test that goes beyond ordinary use, email us
  first.
- Run automated workloads at a scale that disrupts other users. Rate limits
  are there to bound this; intentionally trying to evade them is grounds
  for suspension.

We reserve the right to suspend or terminate accounts that violate
these rules.

## 4. Content

**Your content stays yours.** You retain all rights to projects, files,
sketches, designs, and chat history you create on Kerf. By using the
Service, you grant us a limited license to store, process, and display
your content as needed to operate the Service (e.g. render your projects,
back up your data, send your chat messages to the LLM provider you
chose).

**Public Workshop content.** When you publish a project to the public
Workshop, you grant other users a worldwide, non-exclusive, royalty-free
license to view, fork, and modify your project in the Workshop. You can
unpublish at any time, but copies forked before unpublishing remain with
the user who forked them. We don't claim ownership.

**Content rules:** don't publish content that infringes intellectual
property, contains malware, depicts illegal activity, or harasses other
users. We may remove content that violates these rules.

## 5. Data export and account deletion

- Every project has a "Download project" button that exports all your
  files as a zip.
- You can delete your account from `Profile → Delete Account`. Your
  account data, private projects, and chat history are wiped within 30
  days. Public Workshop publishes stay live unless you unpublish them
  first.

## 6. Service availability

We aim for high availability but don't guarantee it. The Service is
provided **"as is"** without uptime guarantees. Contact
[hello@kerf.sh](mailto:hello@kerf.sh) if you need something bespoke.

We may schedule downtime for maintenance and will give reasonable notice
where possible (in-app notice + status page).

## 7. Third-party providers

Kerf uses third-party services to deliver some features:

- **LLM providers** (Anthropic, OpenAI, Google, DeepSeek, MiniMax) —
  your chat content is sent to whichever you choose.
- **Fly.io** — hosting.
- **Tigris** — object storage (`fly.storage.tigris.dev`).
- **GitHub** (if you configure it as a git remote) — Kerf does not broker
  OAuth or hold your GitHub credentials; you push using your own SSH key
  or PAT, exactly as with the git CLI.

These third parties operate under their own terms. We've chosen each
based on privacy and reliability; full details in our
[Privacy Policy](./privacy.md).

## 8. Liability

To the maximum extent permitted by law:

- The Service is provided "as is" without warranties of any kind.
- We're not liable for indirect, incidental, special, consequential, or
  punitive damages, or lost profits, even if we've been advised of the
  possibility.
- Our total liability for any claim arising from the Service is limited
  to the amount you paid us in the 12 months before the claim, or
  USD 100, whichever is greater.

Nothing in these terms limits liability for fraud, gross negligence,
or other liability that can't be limited by law.

## 9. Changes to these terms

We may update these terms. If we make a change that materially affects
your rights, we'll post a notice in the app at least 30 days before the
change takes effect. Continued use after that date means you accept the
change.

Minor clarifications go in without notice; the change history is visible
on GitHub.

## 10. Governing law

These terms are governed by the laws of the Republic of South Africa.
Disputes are resolved in the courts of Durban, KwaZulu-Natal, unless
you're a consumer in a jurisdiction (EU, UK, etc.) where local consumer
law requires a different forum.

The South African Consumer Protection Act applies where relevant.

## 11. Contact

- **Support**: [support@kerf.sh](mailto:support@kerf.sh)
- **Privacy**: [privacy@kerf.sh](mailto:privacy@kerf.sh)
- **Security**: [security@kerf.sh](mailto:security@kerf.sh) (see
  [SECURITY.md](https://github.com/vul-os/kerf/blob/main/SECURITY.md))
- **Legal / business**: [hello@kerf.sh](mailto:hello@kerf.sh)

Postal address available on request.

---

_2026-07-17: payment/billing provisions removed — kerf has no paid product.
GitHub OAuth-brokering provisions removed — GitHub is used as an ordinary
git remote with your own credentials. See `decisions.md` for the underlying
ADRs._
