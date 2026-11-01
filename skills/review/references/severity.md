# Severity rubric

Severity = likely impact × likelihood in real use. Choose the lower level when unsure.

| Level | Meaning | Merge? | Examples |
|---|---|---|---|
| **blocker** | Will cause an incident, data loss, security breach or broken build/tests. Verified. | No | SQL/command injection from request input; auth check missing on a new endpoint; migration drops a column still read by deployed code; deadlock on the normal path; tests fail; secret committed; GPU kernel reads shared memory before `__syncthreads()` |
| **major** | Real bug or risk on a plausible path; or a missing test for risky new logic. | Not without a fix or explicit acceptance | Off-by-one dropping the last page; unhandled error leaving partial state; race in a cache under concurrent requests; O(n²) on a list that reaches 10⁵; changed function behaviour with un-updated callers; retry without idempotency |
| **minor** | Correct today but fragile, or a bug on an unlikely path; meaningful maintainability cost. | Yes, fix soon | Missing timeout on an internal call; misleading name about units; duplicated validation that must stay in sync; error message leaks an internal path |
| **nit** | Taste, style or tiny polish. Only if house rules/linters care or the user asked for `--strict`. | Yes | Naming consistency, comment typo, import order |

## Confidence
- `high`: traced end-to-end or reproduced.
- `medium`: strong reasoning, but depends on something not visible (caller behaviour, runtime config).
  Say what would confirm it.
- `low`: don't report it as a finding; mention it as a question in the summary if worthwhile.

## Things that are not findings
- Pre-existing problems in unchanged code. Mention them only if the change makes them worse or
  newly reachable, or if they are blockers (then label them "pre-existing").
- Style already enforced by a formatter/linter in CI.
- Alternative designs that are not clearly better for this codebase.
- Speculation about requirements you can't see. Ask instead.
