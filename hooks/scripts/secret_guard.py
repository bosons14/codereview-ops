#!/usr/bin/env python3
"""PostToolUse hook: after Claude writes or edits any file, scan it for hard-coded secrets
(API keys, tokens, private keys, passwords in connection strings) in any language.

Silent when the file is clean. On a hit, exits 2 so the finding is fed back to Claude, which should
move the value to an environment variable / secret store in the same turn.
Disable with CODEREVIEW_OPS_HOOK_DISABLE=1. Allow a specific line with the comment
`codereview-ops: allow-secret`.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from secrets_scan import scan_file  # noqa: E402

SKIP_SUFFIX = {".lock", ".sum", ".svg", ".map"}


def main() -> int:
    if os.environ.get("CODEREVIEW_OPS_HOOK_DISABLE") == "1":
        return 0
    try:
        event = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    ti = event.get("tool_input") or {}
    path = ti.get("file_path") or ti.get("path") or ti.get("notebook_path") or ""
    p = Path(path)
    if not path or not p.is_file() or p.suffix.lower() in SKIP_SUFFIX:
        return 0
    try:
        if p.stat().st_size > 2_000_000:
            return 0
    except OSError:
        return 0
    hits = scan_file(str(p))
    if not hits:
        return 0
    lines = [f"codereview-ops secret guard: {len(hits)} possible secret(s) in {p.name}:"]
    for h in hits[:10]:
        lines.append(f"  line {h['line']}: {h['title']} [{h['match']}]")
    lines.append("Move real secrets to environment variables or a secret manager. If this is a test "
                 "fixture or false positive, add the comment `codereview-ops: allow-secret` on that line.")
    print("\n".join(lines), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
