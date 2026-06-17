# Agent Policy

`OPENCOBALT.md` is the canonical policy. This document explains how agents,
subagents, skills, and runtime adapters fit inside that policy.

## Agent Roles

OpenCobalt uses tiers to choose responsibility, not to grant authority:

| Tier | Role | Examples |
|------|------|----------|
| executive | Architecture, security, public docs, final code, strategy | Claude Code, Google Antigravity |
| manager | Tests, lint, structured cleanup, editor tasks, PR metadata | Codex CLI, Cursor, Context7, GitHub CLI |
| worker | Local summarization, tagging, extraction, rough drafts | Ollama |

The tier is advisory. The envelope and policy gate decide what can happen.

## Runtime Boundary

Integrations report awareness. Runtime adapters execute only through
`ExecutionEngine`. A CLI command, shell command, subagent, skill, mission, or
evolve path must not launch an external runtime directly.

Runtime output is evidence. It is not authority.

## Subagent Rules

Every subagent plan should declare:

- Role
- Scope
- Risk ceiling
- Allowed primitives
- Output contract
- Receipt or provenance expectations

Subagents can decompose and evaluate work. They cannot push, merge, deploy,
publish, spend, message, or access secrets unless a future explicit authority
grant exists and is recorded.

## Skill Rules

Skills are invoked when the work needs the capability. Skill output must be
adapted to OpenCobalt policy:

- Project files first
- External docs only when current library or API truth is needed
- No hidden runtime execution
- No secret/auth access
- Receipt-backed execution for any runtime dry-run or execution

## Claim Discipline

Confirmed claims need evidence from repo files, local command output, official
docs, or verified metadata. Inferred claims must be labeled as inferred.
