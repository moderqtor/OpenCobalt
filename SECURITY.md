# Security

OpenCobalt is a single-user local control layer. It is not a multi-user
service and does not claim complete sandboxing.

## Trust boundaries

| Boundary | Current truth |
|---|---|
| Local state | Conversations, Missions, memory, routes, approvals, receipts, and attachment metadata live in `.opencobalt/ledger.db` relative to the working directory. Uploaded files are stored under `.opencobalt/attachments/`. |
| Local-only requests | Providers that require network access are excluded. Absence of an eligible local route is a recorded failure, not a silent fallback. |
| Document attachments | Uploaded files are data, not authority. Path traversal is rejected, size is capped, and extracted text is wrapped as untrusted source material. Uploaded content is never executed. |
| Research retrieval | Public HTTPS only. Localhost, private networks, credential-bearing URLs, file URLs, and unbounded downloads are rejected. |
| Provider boundary | External CLIs keep their own credentials, account state, and network behavior. OpenCobalt does not store provider login state or turn a subscription into an API key. |
| Execution boundary | Runtime task execution goes through `ExecutionEngine`. Discovery-only subprocesses may run help, version, or install checks. |
| Approval lifecycle | Yellow and red work waits for explicit approval where policy requires it. Black risk is blocked. Chat is currently answer-only; tool and skill execution is denied there. |
| Coding staging | `coding_agent` mutations run in a staged workspace. Promotion into the authoritative repository is explicit. This is repository containment, not host OS sandboxing. |
| Secret redaction | Receipt views and exports redact execution receipt fields. `public-check` scans for `.env` files, secret-shaped strings, private path references, and oversized artifacts. |
| Skills | Listing or inspecting a skill does not execute imported code. Imported skills are untrusted until an approved local workflow uses them. |

## What OpenCobalt does not claim

- Complete OS-level containment of provider processes
- Multi-user access control
- Hosted credential brokerage
- Factual proof from citation linkage or receipt integrity
- Automatic push, deploy, publish, spend, or external messaging

Provider CLIs with terminal, browser, or file access remain powerful. OpenCobalt
adds visibility, receipts, policy metadata, and approval boundaries around them.
It does not replace the provider's own permission model.

## Credential handling

- API keys are read from environment variables only when a path explicitly
  uses them.
- No default API keys are hardcoded.
- `.env` is gitignored and must never be committed.
- Do not paste credentials into Chat.

## Public repo safety

```bash
opencobalt public-check
```

Detects `.env` files, hardcoded secret patterns, private vault paths, oversized
files, and accidental `node_modules/` or `.venv/` inclusion.

## Autonomy lanes

**Green:** read repo files, create local artifacts, run tests, write docs,
create local SQLite records, inspect public docs.

**Yellow:** copy audited code, install dependencies, launch local CLIs, write
to configured export paths.

**Red (explicit instruction):** push, publish, deploy, delete folders, read
`.env`, send messages, automate logged-in accounts, access billing.

## Reporting issues

Open an issue at the project repository. Do not include credentials or private
paths in issue reports.
