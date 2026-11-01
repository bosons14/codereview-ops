---
name: review
description: "This skill should be used when the user asks to \"review my code\", \"review my changes\", \"code review this branch\", \"review before I push/merge\", \"find bugs in this diff\", \"audit this repo\", \"review these files\", or runs /review or /codereview-ops:review. Language-agnostic: works on any language, mix of languages, config or infrastructure code, for a diff, staged changes, a commit range, explicit paths or a whole repository."
argument-hint: "[--base REF | --staged | --range A..B | --paths P... | --all] [--security] [--fix] [--sarif FILE] [--strict]"
metadata:
  version: "0.1.0"
---

# codereview-ops: language-agnostic code review

Review code the way a strong senior engineer does: understand the intent, check the change against
the codebase it lives in, report only real problems with evidence and a concrete fix, and say
plainly what was not checked. Language is a detail: the same process applies to Python, Rust,
Verilog, Terraform or a shell script. Tools supply evidence; judgement decides what matters.

Arguments: $ARGUMENTS

`${CLAUDE_PLUGIN_ROOT}` below is this plugin's directory.

## 1. Scope

Run the collector from the repository root, passing scope flags through from the arguments
(`--base`, `--staged`, `--range`, `--diff-file`, `--paths`, `--all`). With no flags it reviews the
branch since its base plus uncommitted work, or the last commit when the tree is clean.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/collect.py" [scope flags]
```

The summary lists files with languages, changed line ranges, risk tags, secrets on added lines,
detected test/lint commands, project rule files and reviewer batches. Full details are in
`manifest.json` in the printed workdir. If the scope is empty, say so and stop. If the user's
words imply a different scope from what was collected ("just the auth module"), re-run with
`--paths`.

## 2. Context before judgement

- Read every file in "read first": `CODEREVIEW.md` / `.codereview-ops/rules.md` are the project's
  house rules and **override generic advice**; `CLAUDE.md`, `AGENTS.md` and `CONTRIBUTING.md` give
  conventions. `.codereview-ops.json` sets thresholds (see `references/config.md`).
- Work out the intent: commit messages (`git log --format=%s%n%b <base>..HEAD`), the PR description
  if known, the user's words. A review that misunderstands intent is noise.
- Skim neighbours of changed code: callers of changed functions (`grep` the symbol), the interface
  or schema they implement, and tests that cover them. Many real bugs are in the contract between
  changed and unchanged code.

## 3. Evidence from tools

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run_linters.py"
```

It runs only linters already installed (ruff, eslint, go vet, clippy, shellcheck, hadolint, cppcheck,
rubocop, yamllint, verilator and more) and keeps diagnostics on changed lines. Never install tools
without asking. Then, unless the user said not to or the suite is clearly expensive (needs services,
GPUs, >5 minutes), run the project's detected **test command** once. For a large repo, run only the
tests for the changed area if the runner allows it. A failing test caused by the change is
a blocker; a failure that already exists on the base is reported as context, not as a finding.

Treat linter output as leads, not findings: promote a diagnostic only if it is a real defect or
violates the house rules, and merge duplicates into the human finding they belong to.

## 4. Review

**Who reviews.** If this session wrote or edited the code under review, do not grade your own
work: delegate to the `code-reviewer` agent. Otherwise choose by the manifest's `size`:

- `small`: review it here directly.
- `medium` / `large`: launch one `code-reviewer` agent per batch from the manifest, all in a single
  message so they run in parallel (cap at 8; merge the smallest batches if there are more). Give each
  agent the workdir path, the plugin directory (`${CLAUDE_PLUGIN_ROOT}`), its batch's file list, the intent, the house rules and any linter leads for
  its files. Ask for findings in the JSON schema from `references/findings-schema.md`.
- Add one `security-auditor` agent when the risk tags include exec, sql, deserialize, html-injection,
  authz, crypto, filesystem or network, when secrets were found, when a dependency manifest changed,
  or when the user passed `--security`.

**What to check** (each reviewer reads `references/checklist.md` and the parts of
`references/language-notes.md` for the languages in scope):

1. Correctness: logic, edge cases (empty, zero, one, max, null/None/nil, unicode, time zones),
   off-by-one, error paths, the contract with callers, behaviour changes that callers don't expect.
2. Security: untrusted input reaching a sink, authn/authz, secrets, crypto misuse, unsafe
   deserialization, path traversal, SSRF, injection of any kind.
3. Reliability: resource leaks, concurrency and ordering, retries/timeouts, partial failure,
   idempotency, migrations and backward compatibility.
4. Performance: algorithmic complexity on realistic input sizes, N+1 queries, work in hot loops,
   unbounded memory. Only when it plausibly matters.
5. Tests: does a test fail if the change is reverted? Are the new branches covered? The
   `source_changed_without_tests` signal is a prompt to check, not automatically a finding.
6. Maintainability: only where it will cause bugs or real cost later (misleading names, duplicated
   logic that must stay in sync, dead code, API design). Pure style is a nit at most, and only if the
   house rules or an existing linter config cares.

Review the changed lines **in the context of the whole file**. Read a file completely when it is
small, read the changed functions completely when it is large.

## 5. Verify, then rank

False positives destroy trust in a reviewer. Before reporting:

- Every **blocker** and **major** must be verified: re-read the code path, trace the input to the
  sink, check that no guard elsewhere already handles it, and where cheap, prove it (a quick
  script, a failing test, a REPL one-liner). For three or more blocker/major findings, or for a
  large review, hand them to the `finding-verifier` agent, which tries to refute each one.
  Drop what is refuted; downgrade what is plausible but unproven to `confidence: "medium"`.
- Severity follows `references/severity.md`. If in doubt between two levels, pick the lower.
- Apply `min_severity` and `max_findings` from config. With `--strict`, report down to nits.

## 6. Report

Write the merged findings to `<workdir>/findings.json` (schema in `references/findings-schema.md`;
put code suggestions in fenced blocks), then:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/report.py" <workdir>/findings.json [--sarif FILE]
```

Show the user the report: verdict, counts, then findings grouped by severity, each with
`file:line`, why it matters, and the fix. Mention the full report path (`REVIEW.md` in the workdir)
and any evidence gaps ("shellcheck not installed", "tests not run: need Postgres"). Do not pad the
review with praise. One line of "what's good" is fine when it is specific.

## 7. Fix (only when asked)

If the user passed `--fix` or asks for fixes after the report: fix blockers and majors first,
smallest correct change each, keeping the existing style. Re-run the linters and tests and show
before/after. Never auto-fix nits unless asked. Never commit, push or rewrite history unless asked.

## Additional resources

- `references/checklist.md`: universal review checklist by category
- `references/language-notes.md`: pitfalls by language family (native, managed, dynamic, shell,
  query, HDL, infra/config, smart contracts)
- `references/severity.md`: severity rubric with examples
- `references/findings-schema.md`: findings JSON format consumed by `report.py`
- `references/config.md`: `.codereview-ops.json` and `CODEREVIEW.md` reference
