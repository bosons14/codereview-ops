# Project configuration

Both files are optional and live at the repository root.

## `.codereview-ops.json`: thresholds and scope

```json
{
  "base": "origin/main",
  "ignore": ["docs/generated/**", "**/*.snap", "legacy/**"],
  "include_generated": false,
  "min_severity": "minor",
  "fail_on": "major",
  "max_findings": 40,
  "focus": ["security", "correctness"],
  "batch_lines": 700,
  "batch_files": 12,
  "max_file_lines": 4000,
  "linters": { "enabled": true, "disable": ["cppcheck"], "timeout": 120 },
  "rules_file": "docs/review-rules.md"
}
```

| Key | Default | Effect |
|---|---|---|
| `base` | auto (`origin/HEAD`, main, master…) | Branch to diff against |
| `ignore` | lockfiles, vendored, build output, generated protobufs | Extra glob patterns to skip |
| `include_generated` | `false` | Review files marked `@generated` / `DO NOT EDIT` |
| `min_severity` | `nit` | Lowest severity shown in the report |
| `fail_on` | `blocker` | `report.py` exits 1 at/above this (CI gate); `never` to disable |
| `max_findings` | 60 | Cap on reported findings; blockers/majors are never dropped |
| `focus` | `[]` | Categories reviewers should prioritise |
| `batch_lines` / `batch_files` | 700 / 12 | Size of each parallel reviewer's batch |
| `max_file_lines` | 4000 | Above this, full-file audits focus on hotspots |
| `linters.disable` | `[]` | Linter names to skip (see `scripts/run_linters.py`) |
| `rules_file` | none | Extra house-rules file to read |

## `CODEREVIEW.md`: house rules (plain language)

Anything a reviewer on your team would be told on day one. Rules here override the generic checklist.

```markdown
# Review rules
- All DB access goes through `repo/` – flag raw SQL anywhere else (major).
- Public API changes need a CHANGELOG entry (minor).
- We use `Result<T, AppError>`; `unwrap()` outside tests is a major.
- Kernel code: every `cudaMalloc` must have a matching free on all paths.
- Don't comment on formatting – `prettier` and `black` run in CI.
```

Also read if present: `.codereview-ops/rules.md`, `REVIEW_GUIDELINES.md`, `.github/CODEREVIEW.md`,
`CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md`.

Suppress a secret-scanner hit on a line with the comment `codereview-ops: allow-secret`.
