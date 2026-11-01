# codereview-ops

**Language-agnostic code review for [Claude Code](https://claude.com/claude-code).** Point it at a
diff, a branch, a pull request, a few files or a whole repository, in any language or mix of
languages, and get a review that reads like it came from a careful senior engineer: real bugs with
evidence and a concrete fix, nothing invented, and an honest list of what wasn't checked.

Part of the `*-ops` family alongside [eda-ops](https://github.com/bosons14/eda-ops).

## Why language-agnostic works

Claude already reads Python, Rust, Go, TypeScript, C++/CUDA, Verilog, Terraform, SQL, shell and
everything in between. What a reviewer needs on top of that is not language-specific. It needs
**process**:

1. **Scope precisely**: which files and which lines changed, what's generated or vendored, which
   languages are present, where the risk is (`scripts/collect.py`, 150+ extensions, shebangs and
   special filenames).
2. **Gather evidence**: run whatever linters are already installed and the project's own test
   command, and keep only diagnostics on changed lines (`scripts/run_linters.py`, 20+ linters).
3. **Review independently and in parallel**: big changes are split into batches and each batch goes
   to a fresh `code-reviewer` agent that didn't write the code. Risky surface area also gets a
   `security-auditor` agent.
4. **Verify adversarially**: a `finding-verifier` agent tries to *refute* every blocker/major
   before it reaches you. False positives are what make people ignore reviewers.
5. **Report in useful formats**: Markdown, SARIF (GitHub code scanning), GitHub annotations, a
   PR-review API payload with inline comments, and a CI exit code (`scripts/report.py`).

Language knowledge lives in a compact reference (`skills/review/references/language-notes.md`) organised by
*family* (native/GPU, managed, dynamic, shell, query, HDL, infra/config, smart contracts), so adding a
language is one line in `scripts/languages.py`.

## What's inside

| Component | Name | What it does |
|---|---|---|
| Skill | `/codereview-ops:review` | Full review of a branch, staged changes, commit range, paths or whole repo, with optional `--fix` |
| Skill | `/codereview-ops:security-review` | Threat-driven security pass: secrets, injection, authz, crypto, deps, CI and IaC |
| Skill | `/codereview-ops:pr-review` | Review a GitHub/GitLab PR in a side worktree; post inline comments only with `--post` |
| Agent | `code-reviewer` | Independent reviewer for one batch of files; returns findings JSON |
| Agent | `security-auditor` | Taint-tracing security reviewer with CWE ids |
| Agent | `finding-verifier` | Tries to disprove findings; marks confirmed / refuted / unproven |
| Hook | secret guard | After every Write/Edit, scans the file for API keys, tokens, private keys and hard-coded passwords |
| Scripts | `collect.py`, `run_linters.py`, `report.py`, `secrets_scan.py` | Python 3.9+ standard library only; no dependencies |

## Install

```bash
# from GitHub
claude plugin marketplace add bosons14/codereview-ops
claude plugin install codereview-ops@codereview-ops

# or try it from a local clone without installing
claude --plugin-dir /path/to/codereview-ops
```

Requirements: Python 3.9+ and git. Linters are optional and used only if already installed. `gh`
is needed for PR review.

## Use

Inside Claude Code, in your repository:

```text
/codereview-ops:review                       # branch vs base + uncommitted (or last commit)
/codereview-ops:review --staged              # before committing
/codereview-ops:review --base origin/develop
/codereview-ops:review --range HEAD~5..HEAD
/codereview-ops:review --paths src/auth kernels/gemm.cu
/codereview-ops:review --all                 # full-repo audit
/codereview-ops:review --fix                 # review, then fix blockers/majors and re-run tests
/codereview-ops:review --sarif review.sarif
/codereview-ops:security-review --all
/codereview-ops:pr-review 128                # report in chat
/codereview-ops:pr-review 128 --post         # …and post inline comments to the PR
```

Or just ask: *"review my changes before I push"*, *"security audit the payments service"*,
*"review PR 128"*.

### Severity

🔴 **blocker**: will cause an incident, breach, data loss or broken build. 🟠 **major**: real bug
on a plausible path. 🟡 **minor**: fragile or costly later. ⚪ **nit**: taste (hidden unless
`--strict` or house rules care). Verdict: *APPROVE*, *APPROVE WITH NITS* or *REQUEST CHANGES*.

## Configure (optional)

- **`CODEREVIEW.md`** at the repo root: your team's house rules in plain language. They override
  the generic checklist. See [`examples/CODEREVIEW.md`](examples/CODEREVIEW.md).
- **`.codereview-ops.json`**: base branch, ignore globs, `min_severity`, `fail_on`,
  `max_findings`, batch sizes, linters to disable. See
  [`skills/review/references/config.md`](skills/review/references/config.md).
- `CODEREVIEW_OPS_HOOK_DISABLE=1` turns off the secret guard. Add the comment
  `codereview-ops: allow-secret` to whitelist a fixture line.

All working files (`manifest.json`, `diff.patch`, `lint.json`, `findings.json`, `REVIEW.md`) go in
`.git/codereview-ops/`, so your working tree stays clean.

## CI

[`examples/github-actions-review.yml`](examples/github-actions-review.yml) runs the review headlessly on
every PR, uploads SARIF to code scanning, annotates the diff and fails the job at your `fail_on`
threshold.

The scripts also work standalone:

```bash
python3 scripts/collect.py --base origin/main      # scope + languages + secrets + risk signals
python3 scripts/run_linters.py                      # installed linters, changed lines only
python3 scripts/report.py findings.json --sarif out.sarif --github-annotations --fail-on major
python3 scripts/secrets_scan.py path/to/file
```

## Development

```bash
python -m pytest -q tests
claude plugin validate .
```

## License

MIT © Subhendra Basu
