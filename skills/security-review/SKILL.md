---
name: security-review
description: "This skill should be used when the user asks for a \"security review\", \"security audit\", \"is this code safe\", \"check for vulnerabilities\", \"find injection bugs\", \"check for secrets\", \"OWASP review\", or runs /security-review or /codereview-ops:security-review, for code in any language, including infrastructure, CI and dependency changes."
argument-hint: "[--base REF | --staged | --paths P... | --all]"
metadata:
  version: "0.1.0"
---

# codereview-ops: security review

A focused, threat-driven pass. Use the same scope machinery as the general review, but spend the
whole budget on exploitable paths.

Arguments: $ARGUMENTS

1. **Scope.** `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/collect.py" [scope flags]`. For "is this
   service safe" questions with no diff, use `--all` (or `--paths` for the service directory).
2. **Secrets first.** Every scanner hit in the summary: open the line, decide real vs fixture/false
   positive. A real secret in a committed file is a **blocker** even after deletion. The fix includes
   rotating the credential and purging history, not just removing the line.
3. **Dependencies.** If manifests changed, list added/upgraded packages. Run an installed auditor
   (`npm audit --omit=dev`, `pip-audit`, `cargo audit`, `govulncheck ./...`, `bundle audit`,
   `osv-scanner`) if available. Don't install one without asking. Sanity-check new package names
   for typosquats.
4. **Deep pass.** Launch the `security-auditor` agent (pass it the workdir, the codereview-ops plugin
   directory `${CLAUDE_PLUGIN_ROOT}`, the file list and the intent). For a large scope, split by
   component (one agent per service/package, in parallel, max 6).
5. **Verify.** Send every blocker/major to the `finding-verifier` agent. Report refuted ones nowhere;
   report unproven ones with `confidence: "medium"` and what would confirm them.
6. **Report.** Write `<workdir>/findings.json` and run `scripts/report.py` (add `--sarif` for GitHub
   code scanning). Order by exploitability. For each finding include the CWE id, attacker
   precondition, impact and fix. End with a short "attack surface reviewed" list and what was out of
   scope.

Use `../review/references/checklist.md` (Security and Config sections) and
`../review/references/language-notes.md` for per-language sinks.
