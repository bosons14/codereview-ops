# Findings JSON schema

Reviewer agents return, and the orchestrator writes to `<workdir>/findings.json`, this structure.
`report.py` validates it, de-duplicates on (file, line, title), applies thresholds and renders
Markdown / SARIF / GitHub annotations / a PR-review payload.

```json
{
  "summary": "2–4 sentences: what the change does, overall assessment, the most important risk.",
  "findings": [
    {
      "severity": "blocker | major | minor | nit",
      "category": "correctness | security | reliability | concurrency | performance | tests | maintainability | api | docs | build | style",
      "file": "path/relative/to/repo/root.ext",
      "line": 42,
      "end_line": 47,
      "title": "Short imperative statement of the problem (≤ 80 chars)",
      "detail": "Why it is wrong: the concrete failure scenario (input/state → wrong result) and its impact. Reference other files/lines as path:line.",
      "suggestion": "Prose, or a fenced code block with the replacement:\n```python\nsubprocess.run([\"ls\", path], check=True)\n```",
      "confidence": "high | medium",
      "verified": true,
      "evidence": "How it was confirmed: test output, trace, linter id (optional)",
      "pre_existing": false
    }
  ],
  "strengths": ["Optional, specific, at most 2"],
  "checks_run": ["ruff (0 in scope)", "npm test: 214 passed"],
  "not_checked": ["shellcheck not installed", "integration tests need Postgres"]
}
```

Rules:
- `file` must be repo-relative, and `line` must be a line in the **new** version of the file, so
  that annotations and PR comments land on the right line. Omit `line` for file-level findings.
- One finding per root cause. If the same bug appears in 5 places, report it once and list the other
  locations in `detail`.
- `suggestion` must be minimal and compile-ready in the file's language and style. Put code in
  fenced blocks with a language tag.
- Do not include findings with `confidence: low`.
