#!/usr/bin/env python3
"""Language-agnostic secret scanner (regex + entropy). Values are always masked in output.

Usage:
  secrets_scan.py FILE [FILE...]          scan whole files, print JSON findings
  secrets_scan.py --stdin                 scan text from stdin
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

RULES: list[tuple[str, str, re.Pattern]] = [
    ("private-key", "Private key block", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----")),
    ("aws-access-key", "AWS access key ID", re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|ANPA|ANVA)[0-9A-Z]{16}\b")),
    ("aws-secret-key", "AWS secret access key", re.compile(r"(?i)aws.{0,20}?(?:secret|private).{0,20}?['\"=:\s]([A-Za-z0-9/+=]{40})\b")),
    ("github-token", "GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b")),
    ("gitlab-token", "GitLab token", re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}\b")),
    ("slack-token", "Slack token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}\b")),
    ("slack-webhook", "Slack webhook URL", re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/]{20,}")),
    ("google-api-key", "Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("stripe-key", "Stripe secret key", re.compile(r"\b(?:sk|rk)_live_[0-9A-Za-z]{20,}\b")),
    ("anthropic-key", "Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b")),
    ("openai-key", "OpenAI API key", re.compile(r"\bsk-(?!ant-)(?:proj-)?[A-Za-z0-9_\-]{32,}\b")),
    ("hf-token", "Hugging Face token", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b")),
    ("npm-token", "npm token", re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")),
    ("twilio-key", "Twilio API key", re.compile(r"\bSK[0-9a-fA-F]{32}\b")),
    ("sendgrid-key", "SendGrid API key", re.compile(r"\bSG\.[A-Za-z0-9_\-]{22}\.[A-Za-z0-9_\-]{43}\b")),
    ("jwt", "JSON Web Token", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")),
    ("db-url-password", "Credentials in connection URL", re.compile(r"\b[a-z][a-z0-9+.\-]{1,20}://[^\s:/@'\"]{1,64}:([^\s@'\"/]{4,})@[^\s'\"]+")),
]

# key = "value" style assignments where the key name suggests a secret.
ASSIGNMENT = re.compile(
    r"(?i)\b([A-Za-z0-9_.\-]*(?:password|passwd|pwd|secret|token|api[_\-]?key|apikey|access[_\-]?key|auth|credential|private[_\-]?key)[A-Za-z0-9_.\-]*)"
    r"\s*(?::=|=>|=|:)\s*['\"]([^'\"\s]{8,})['\"]"
)
PLACEHOLDER = re.compile(
    r"(?i)^(?:x+|\*+|\.+|<.*>|\$\{.*\}|\{\{.*\}\}|%\(.*\)s|changeme|change_me|example|sample|dummy|test|fake|"
    r"placeholder|your[_\-].*|xxx.*|redacted|none|null|undefined|password|secret|todo|env\(.*|process\.env.*|os\.environ.*)$"
)


def entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = {c: s.count(c) for c in set(s)}
    return -sum(n / len(s) * math.log2(n / len(s)) for n in counts.values())


def mask(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "…" + "*" * 4 + value[-2:]


def scan_line(line: str) -> list[dict]:
    hits: list[dict] = []
    if "codereview-ops: allow-secret" in line or "pragma: allowlist secret" in line:
        return hits
    for rule_id, title, rx in RULES:
        m = rx.search(line)
        if m:
            value = m.group(1) if m.groups() else m.group(0)
            hits.append({"rule": rule_id, "title": title, "match": mask(value)})
    if not hits:
        m = ASSIGNMENT.search(line)
        if m:
            value = m.group(2)
            if not PLACEHOLDER.match(value) and entropy(value) >= 3.0 and not value.startswith(("http://", "https://", "/")):
                hits.append({"rule": "hardcoded-credential", "title": f"Hard-coded credential in '{m.group(1)}'",
                             "match": mask(value)})
    return hits


def scan_text(text: str, path: str = "<stdin>", only_lines: set[int] | None = None) -> list[dict]:
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        if only_lines is not None and i not in only_lines:
            continue
        if len(line) > 4000:  # minified blobs
            line = line[:4000]
        for hit in scan_line(line):
            out.append({"file": path, "line": i, **hit})
    return out


def scan_file(path: str, only_lines: set[int] | None = None) -> list[dict]:
    try:
        data = Path(path).read_bytes()
    except OSError:
        return []
    if b"\x00" in data[:8192]:
        return []
    return scan_text(data.decode("utf-8", errors="replace"), path, only_lines)


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help"}:
        print(__doc__)
        return 0
    findings = scan_text(sys.stdin.read()) if argv[0] == "--stdin" else [f for p in argv for f in scan_file(p)]
    print(json.dumps(findings, indent=2))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
