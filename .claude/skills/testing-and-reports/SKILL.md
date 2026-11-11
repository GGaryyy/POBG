---
name: testing-and-reports
description: This skill should be used when writing or running tests for this project, or when generating the test, security, or code-review reports after an implementation task. Covers test tiers by change size, test rules, the security scan scope, and the three report templates written to docs/reports/.
---

# Testing & Reports

## Test tiers — scale to the change

| Change size | Required tests |
|-------------|----------------|
| Small fix / minor change | Unit + integration for the touched code |
| New feature | Unit + integration + E2E for the affected workflow |
| Release, milestone, or performance-sensitive change | Full suite: unit, integration, stress, E2E, security |

Stress tests: report only measured numbers (throughput, latency p50/p95/p99, error rate). If the environment cannot produce a real measurement, state that explicitly — never estimate or fabricate metrics.

## Test layout

Tests go in `tests/`, mirroring the `src/` structure. `tests/fixtures/` holds synthetic, schema-identical sample data (freely readable — real data in `data/` never appears in tests).

| Type | Directory | Purpose |
|------|-----------|---------|
| Unit | `tests/unit/` | Individual functions and methods in isolation |
| Integration | `tests/integration/` | Interactions between modules, APIs, and databases |
| Stress | `tests/stress/` | Performance under high load, concurrency, edge-case volumes |
| E2E | `tests/e2e/` | Complete user workflows end-to-end |
| Security | `tests/security/` | Defensive scans of this project's own code (scope below) |

## Test rules
- Write tests from the plan's acceptance criteria and key test cases, before or alongside implementation — the plan defines what must pass; the implementation exists to make those tests pass. Never defer testing to later.
- Every public function/method has at least one unit test. Every API endpoint has integration tests covering success and error cases.
- Tests use `tests/fixtures/` synthetic data, never `data/`.
- Naming: `test_<module_name>.py` (Python), `<module_name>.test.ts` (JS/TS).
- Tests must be runnable independently — no shared mutable state. Include both positive (happy path) and negative (error/edge) cases. Assertions must check actual values and behaviour — not just status codes or not-None.
- Run the required tier before marking a task complete. Report pass/fail counts and coverage to the user. Fix failures before proceeding.

## Security scan scope

These are defensive checks on this project's own code and dependencies.

| Category | What to check |
|----------|---------------|
| OWASP Top 10 | Injection, XSS, CSRF, SSRF, insecure deserialization, broken auth, sensitive data exposure, security misconfiguration, broken access control, logging failures |
| Dependency scan | Known CVEs in third-party packages (`pip audit`, `npm audit`, or equivalent) |
| Static analysis (SAST) | Code-level vulnerability patterns: hardcoded credentials, unsafe eval, path traversal, etc. |
| Secret leak detection | API keys, tokens, passwords, private keys in source or config files |
| Privacy | Code paths that write or return ladder character or account names |

- Never commit secrets or credentials — use `.env` files listed in `.gitignore`.
- Findings carry a severity (Critical / High / Medium / Low). Critical and High must be resolved before completion.
- Log security findings in `docs/issues/` with a `[Security]` prefix in the title.

## Reports

Written to `docs/reports/`, date-stamped `YYYY-MM-DD` (same-day repeats append `_02`). Generate after the required test tier passes, in this order:

**1. `test_report_YYYY-MM-DD.md`**
- Execution summary (total / passed / failed / skipped)
- Coverage (line, branch, function)
- Per-category breakdown for the tiers that ran
- Stress metrics only if actually measured
- Details of any failures fixed during the run

**2. `security_report_YYYY-MM-DD.md`** — only for tiers that ran security tests
- Executive summary (pass/fail, findings by severity)
- OWASP check results, dependency CVEs (package, CVE ID, severity, fix version)
- SAST findings (file, line, type, severity), secret-leak results, privacy findings
- Remediation actions taken

**3. `code_review_YYYY-MM-DD.md`**
- Review scope (files reviewed, lines changed)
- Quality assessment (readability, maintainability, complexity), convention compliance, performance notes
- Test-quality audit: bugs the current tests would not catch, hollow assertions, coverage gaps
- Findings table (file, line, severity, description, recommendation)
- Verdict: Approved / Approved with Notes / Needs Revision

## Completion gate

Required tier passes → reports for that tier generated → changelog updated (see `project-docs` skill) → task complete.
