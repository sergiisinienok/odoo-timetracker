# 0009 — The integration user has no access to `mail.mail`

Status: decided — option 1 (grant a group). Waiting on the grant, then re-run the probe.

## What the probe found

`tools/p2s07-probe_mail_mail.py`, run against the trial
(edu-timetracking.odoo.com) as the integration user (uid 5):

- `check_access_rights` on `mail.mail` returns `False` for read, create, write
  and unlink.
- The fields themselves exist as expected (`subject`, `body_html`, `email_to`,
  `email_from`, `recipient_ids`, `auto_delete`, `state`, `failure_reason`).
- The integration user's own `email` is set, so a sender address is not the
  problem.

## Why it matters

Step 2.7 has the worker build a daily digest and send it through Odoo's mail
server via `mail.mail`. As provisioned, the integration user cannot do that.
`mail.mail` is normally restricted to the Settings / Administration group.

## Options

1. **Grant the integration user a group that can create `mail.mail`.**
   Smallest code change, but it widens a service account's privileges for one
   email a day. Would also need repeating on the real sandbox and production.
2. **Post to the chatter instead** (`message_post` on a record, or `mail.message`
   to an ops partner). Regular users can normally do this, so probably no new
   group. Needs a probe first, and the email only goes out if the recipient's
   notification preference is email.
3. **Send from the app over SMTP** with its own credentials. No Odoo privilege
   change, but adds SMTP config to `.env` and a second mail path outside Odoo.

## Decision

Option 1. The grant is made by a human in the Odoo UI (Settings → Users →
integration user), not by the integration user over the API. Afterwards re-run
`tools/p2s07-probe_mail_mail.py`; it must show `create: True` before the
digest is built. Repeat on the real sandbox and on production, and add the
group to the provisioning notes next to the Timesheets / Project / Sales grants.

## Outcome

Grant made on the trial 2026-09-24. Re-probe: `mail.mail` read True, create True,
write False, unlink False. Repeat the same grant on the real sandbox and production.
