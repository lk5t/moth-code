# Security, permissions & owner policy

## v0.2 changes

- **Content policy** moved to the MOTH Server. It is Owner-only (Owner Dashboard → Policy) and applied to every MOTH
  Cloud request, before metering. There is no local policy editor any more. The rule format below is unchanged.
- **Cloud consent.**
  - Chat requires a signed-in MOTH account.
  - The agent asks once **per workspace** before sending any file contents or command output to MOTH Cloud.
  - Credentials are always redacted, and MOTH Cloud never uses user projects as training data.
- **Accounts and server security.** See [SERVER.md](SERVER.md#security-notes): Argon2id, hashed tokens, rate
  limits, no enumeration, isolated worker credentials, Owner re-authentication, audit log. Desktop session tokens
  live in Windows Credential Manager.

MOTH Code separates two things that are often conflated:

| | Owner content policy | Operational security |
| --- | --- | --- |
| Purpose | How MOTH *talks*: persona, generation defaults, topics the owner wants blocked, flagged or masked | Protecting the user's machine, data and privacy |
| Default | No topic restrictions | Always on |
| Who controls it | The project owner (Settings → Content policy, `policy.json`) | Built into MOTH Code; content-policy edits cannot disable it |
| Code | `moth/policy/engine.py` | `moth/security/`, `moth/inference/router.py`, `moth/community/` |

## Owner content policy

`policy.json` has these fields:

- `system_prompt`
- `generation_defaults`
- `content_rules[]`, where each rule has:
  - `id`
  - `applies_to`: `input` | `output` | `both`
  - `match.type`: `keywords` (whole word) | `regex`
  - `match.patterns`
  - `action`: `block` | `warn` | `redact`
  - an optional `message`

Rules are validated on save, and invalid regexes or actions are rejected. When output rules exist, streamed output is
filtered as it is generated, and a `block` stops generation.

## Operational protections

**Workspace boundaries.** The agent can only touch paths that resolve, after symlinks, inside a folder you opened as
a workspace. Paths outside it are denied.

**Approvals.** These always show an approval dialog. The agent waits, and a denial is reported back to it:

| Action | When |
| --- | --- |
| Deleting files | always |
| Destructive commands | e.g. `rm -rf`, `del /s`, `Remove-Item -Recurse`, `git reset --hard`, `git clean -f`, `git push --force`, `format`, `shutdown`, `DROP TABLE` |
| Publishing | `git push`, `npm`/`cargo`/`poetry publish`, `twine upload`, `docker push`, `gh release create` |
| Network access | `curl`, `wget`, `Invoke-WebRequest`, `ssh`, `scp` |
| Reading credential-like files | `.env`, private keys, `.ssh/`, `.aws/`, `credentials.json`, … |
| Local Git commits | unless you allowed them in Settings |
| Remote inference | sending messages or project data to MOTH Cloud needs explicit consent |

You can additionally require approval for all file writes or all commands (Settings → Agent permissions).

**Credential redaction.** Private keys, cloud and API tokens, JWTs and `*_SECRET=`/`*_TOKEN=` style assignments are
redacted from anything sent to MOTH Cloud.

**Never uploaded.** Community contributions contain only weight deltas computed on coordinator-supplied public
shards, and personal-learning data stays local. Secret files are never indexed for retrieval or used as training
sources.

**Local API.** The backend listens on `127.0.0.1` only, on a random port, and requires a random per-launch bearer
token, so other local programs cannot drive the agent.

**Token injection.** File contents, tool output and external text can never produce special control tokens (see
`Message.allow_special`).

**Honesty.** The agent reports `model_incapable` instead of claiming success. Its summary is shown separately from
the verified record of changes, commands and test results.

## Reporting vulnerabilities

Please open a private security advisory on the GitHub repository rather than a public issue.
