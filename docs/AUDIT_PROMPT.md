# Audit Prompt for Codex CLI or Google Antigravity CLI

Use this prompt to have an external AI agent review OpenCobalt before treating the repo as fully public-ready.

---

## For Codex CLI

```
codex "You are auditing the OpenCobalt repository at ~/dev/OpenCobalt for public readiness.

This is a local-first AI orchestration and memory control plane built for a public GitHub portfolio.

Please complete the following audit and write your findings to docs/audits/002-external-audit.md:

Context Sentinel: when producing any final report for Colin, begin with
"Colin, COBALT-SENTINEL: receipts-first." Then state current branch, base
branch or main SHA if known, test baseline, whether worktree is clean, and
whether anything was pushed or merged. If you cannot determine a fact, say so.
Do not invent repository state.

1. PUBLIC SAFETY SCAN
   Run: opencobalt public-check
   Also run: find . -name '.env' -not -name '.env.example'
   Also run: grep -r 'cobaltos-vault' src/ --include='*.py' -l
   Report any issues found. If none, state that explicitly.

2. CREDENTIAL SCAN
   Search all Python, TOML, YAML, and Markdown files for patterns that look like
   hardcoded credentials, API keys, or passwords. Report file and line number for
   any match. Do NOT print the values -- just report where they are.

3. TEST COVERAGE REVIEW
   Run: python3 -m pytest tests/ -v
   Report: which modules are tested, which are not, and which critical behaviors
   are missing test coverage.

4. CODE QUALITY REVIEW
   Read src/opencobalt/core/*.py and src/opencobalt/cli.py.
   Flag any of the following:
   - Functions that could crash with an unhandled exception on normal user input
   - Missing type annotations on public functions
   - Files that are doing too much (more than one clear responsibility)
   - Any code that references private paths (~/cobaltos-vault, ~/dev/AI, etc.)

5. README REVIEW
   Read README.md.
   Check for: em dashes, emojis, inflated claims, vague benefit copy,
   broken links, claims that are not verifiable from the code.
   Report specific line numbers for any issues.

6. DOCS COMPLETENESS
   Verify that all files listed in docs/ are present and non-empty.
   Flag any placeholder or stub sections that claim to document something
   but contain no real content.

7. INSTALL VERIFICATION
   Run: pip install -e '.[dev]' --dry-run
   Run: opencobalt --help
   Run: opencobalt status
   Confirm the package installs cleanly and the CLI responds correctly.

8. FINAL VERDICT
   Based on the above, state clearly:
   - READY: no blockers, safe to be a public portfolio repo
   - NEEDS FIXES: list specific blockers that must be resolved before public posting
   - CONCERNS: list non-blocking issues worth addressing after initial posting

Write your full findings to docs/audits/002-external-audit.md using plain prose.
No em dashes. No emojis. No inflated language."
```

---

## For Google Antigravity CLI

Use this form only when `opencobalt doctor antigravity` reports
`non_interactive_mode` as `runtime_discovered`. Otherwise paste the prompt into an
interactive `agy` session.

```
agy --print "You are performing a public readiness audit of a Python repository called OpenCobalt.

The repo is at ~/dev/OpenCobalt. It is intended as a public portfolio project for a
USC undergraduate with an Applied Analytics minor who builds AI-native tooling.

Read every file in the repository. Then answer the following questions in a single
structured report. Write your report to docs/audits/002-external-audit.md.

Context Sentinel: when producing any final report for Colin, begin with
"Colin, COBALT-SENTINEL: receipts-first." Then state current branch, base
branch or main SHA if known, test baseline, whether worktree is clean, and
whether anything was pushed or merged. If you cannot determine a fact, say so.
Do not invent repository state.

SECTION 1: WHAT THIS PROJECT CLAIMS TO BE
Summarize in 2-3 sentences what OpenCobalt is, based on the README and docs.
Then state whether the code actually supports those claims. Be specific.

SECTION 2: PUBLIC SAFETY
- Are there any .env files (other than .env.example)?
- Are there any hardcoded credentials, passwords, or API keys in source files?
- Are there references to private paths (~/cobaltos-vault, ~/dev/AI, memory_store, vault_index)?
- Is the .gitignore correctly excluding runtime artifacts?
State CLEAN or list specific issues with file paths.

SECTION 3: TEST QUALITY
Read tests/*.py in full.
- Do the tests verify real behavior or just that code runs without errors?
- Are edge cases covered (missing Ollama, empty database, bad input)?
- What is not tested that should be?
Be specific. Cite test function names.

SECTION 4: CODE REVIEW
Read src/opencobalt/core/*.py and src/opencobalt/cli.py.
- Is the module decomposition appropriate?
- Are there any obvious bugs or unhandled failure modes?
- Does the router correctly implement the tier classification described in docs/TOOL_ROUTING.md?
- Does the ledger correctly implement the schema described in docs/ARCHITECTURE.md?
- Is there anything that would embarrass a developer showing this to a technical interviewer?

SECTION 5: DOCUMENTATION ACCURACY
Read all files in docs/.
- Does docs/ARCHITECTURE.md accurately describe the code?
- Does docs/TOOL_ROUTING.md match the actual router implementation?
- Are there any docs that make claims the code does not support?

SECTION 6: EMPLOYER PRESENTATION
Read docs/EMPLOYER_README_NOTES.md and docs/PORTFOLIO_SUMMARY.md.
- Are the resume bullets accurate and verifiable?
- Are there any overclaims?
- What would a technical interviewer push back on?

SECTION 7: FINAL VERDICT
State one of:
- READY TO POST: no changes needed
- POST WITH NOTES: safe to post, list what to mention in the PR description or caveat
- NEEDS FIXES FIRST: list specific issues that must be resolved

Use plain language. No em dashes. No emojis. Cite specific file:line references for all findings."
```

---

## Running the Audit

From the OpenCobalt root directory:

```bash
# Using Codex CLI
cd ~/dev/OpenCobalt
codex < docs/AUDIT_PROMPT.md

# Or paste the prompt section directly:
codex "You are auditing..."

# Using Google Antigravity CLI
agy --print "You are performing a public readiness audit..."
```

The audit output will be written to:
`docs/audits/002-external-audit.md`

After the audit, commit it:

```bash
git add docs/audits/002-external-audit.md
git commit -m "docs: add external audit findings"
git push
```
