#!/usr/bin/env python3
"""codereview-ops: run whatever linters/analyzers are installed for the languages in scope.

Reads the manifest written by collect.py, picks linters by language, runs only the ones present on
PATH (or in the project's node_modules/.bin / .venv/bin), normalises `file:line[:col]: message` output
and keeps only diagnostics on changed lines (unless --all-lines). Nothing is installed; missing tools
are reported so the review can say which evidence was unavailable.

Usage:
  run_linters.py [--manifest PATH] [--all-lines] [--only ruff,shellcheck] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# name, languages, argv template ({files} expands to the file list), optional config-file requirement
LINTERS: list[dict] = [
    {"name": "ruff", "langs": {"Python"}, "cmd": ["ruff", "check", "--output-format=concise", "--no-cache", "{files}"]},
    {"name": "flake8", "langs": {"Python"}, "cmd": ["flake8", "{files}"], "fallback_for": "ruff"},
    {"name": "eslint", "langs": {"JavaScript", "JavaScript (JSX)", "TypeScript", "TypeScript (TSX)", "Vue", "Svelte"},
     "cmd": ["eslint", "--format", "unix", "--no-error-on-unmatched-pattern", "{files}"],
     "needs_any": ["eslint.config.js", "eslint.config.mjs", "eslint.config.cjs", "eslint.config.ts", ".eslintrc",
                   ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.json", ".eslintrc.yml", ".eslintrc.yaml"]},
    {"name": "biome", "langs": {"JavaScript", "JavaScript (JSX)", "TypeScript", "TypeScript (TSX)", "JSON"},
     "cmd": ["biome", "lint", "--reporter=github", "{files}"], "needs_any": ["biome.json", "biome.jsonc"]},
    {"name": "go vet", "langs": {"Go"}, "cmd": ["go", "vet", "{pkgdirs}"], "needs_any": ["go.mod"]},
    {"name": "staticcheck", "langs": {"Go"}, "cmd": ["staticcheck", "{pkgdirs}"], "needs_any": ["go.mod"]},
    {"name": "clippy", "langs": {"Rust"}, "cmd": ["cargo", "clippy", "--quiet", "--message-format=short", "--all-targets"],
     "needs_any": ["Cargo.toml"], "slow": True},
    {"name": "shellcheck", "langs": {"Shell"}, "cmd": ["shellcheck", "-f", "gcc", "{files}"]},
    {"name": "hadolint", "langs": {"Dockerfile"}, "cmd": ["hadolint", "--format", "tty", "--no-color", "{files}"]},
    {"name": "rubocop", "langs": {"Ruby"}, "cmd": ["rubocop", "--format", "emacs", "--force-exclusion", "{files}"]},
    {"name": "php -l", "langs": {"PHP"}, "cmd": ["php", "-l", "{file}"], "per_file": True},
    {"name": "cppcheck", "langs": {"C", "C++", "C/C++ header", "CUDA"},
     "cmd": ["cppcheck", "--quiet", "--enable=warning,performance,portability", "--inline-suppr",
             "--template={file}:{line}:{column}: {severity}: {message} [{id}]", "{files}"]},
    {"name": "yamllint", "langs": {"YAML", "YAML (GitHub Actions)", "YAML (GitLab CI)"},
     "cmd": ["yamllint", "-f", "parsable", "{files}"]},
    {"name": "actionlint", "langs": {"YAML (GitHub Actions)"}, "cmd": ["actionlint", "-no-color", "{files}"]},
    {"name": "luacheck", "langs": {"Lua"}, "cmd": ["luacheck", "--formatter", "plain", "--codes", "{files}"]},
    {"name": "ktlint", "langs": {"Kotlin"}, "cmd": ["ktlint", "--relative", "{files}"]},
    {"name": "swiftlint", "langs": {"Swift"}, "cmd": ["swiftlint", "lint", "--quiet", "{files}"]},
    {"name": "tflint", "langs": {"Terraform"}, "cmd": ["tflint", "--format", "compact"]},
    {"name": "sqlfluff", "langs": {"SQL"}, "cmd": ["sqlfluff", "lint", "--format", "github-annotation-native", "--nofail", "{files}"],
     "needs_any": [".sqlfluff", "setup.cfg", "pyproject.toml", "tox.ini"]},
    {"name": "verilator", "langs": {"Verilog", "SystemVerilog"},
     "cmd": ["verilator", "--lint-only", "-Wall", "-Wno-fatal", "-Wno-DECLFILENAME", "-Wno-MULTITOP", "{file}"], "per_file": True},
    {"name": "markdownlint", "langs": {"Markdown"}, "cmd": ["markdownlint", "{files}"],
     "needs_any": [".markdownlint.json", ".markdownlint.yaml", ".markdownlint.yml", ".markdownlintrc"]},
]

DIAG = re.compile(r"^(?:%Warning-[A-Z0-9_]+: |%Error(?:-[A-Z0-9_]+)?: )?(?P<file>[^\s:][^:\n]*?):(?P<line>\d+)(?::(?P<col>\d+))?(?::\d+)?[:\s]\s*(?P<msg>.+)$")
GH_ANNOT = re.compile(r"^::(?P<sev>error|warning|notice) file=(?P<file>[^,]+),line=(?P<line>\d+)(?:,(?:col|column)=(?P<col>\d+))?[^:]*::(?P<msg>.+)$")
HADOLINT = re.compile(r"^(?P<file>[^:\s]+):(?P<line>\d+)\s+(?P<msg>DL\d+.+|SC\d+.+)$")


def resolve(exe: str, root: Path) -> str | None:
    for cand in (root / "node_modules" / ".bin" / exe, root / ".venv" / "bin" / exe, root / "venv" / "bin" / exe):
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    return shutil.which(exe)


def parse(output: str, root: Path) -> list[dict]:
    diags = []
    for line in output.splitlines():
        line = line.rstrip()
        m = GH_ANNOT.match(line) or HADOLINT.match(line) or DIAG.match(line)
        if not m:
            continue
        f = m.group("file").strip()
        if f.startswith(("http", "/dev/")) or re.search(r"\s", f):  # out-of-scope paths are dropped later
            continue
        p = Path(f)
        try:
            rel = os.path.relpath(p if p.is_absolute() else (root / p), root)
        except ValueError:
            rel = f
        msg = m.group("msg").strip()
        sev = (m.groupdict().get("sev") or "").lower()
        if not sev:
            low = msg.lower()
            sev = "error" if re.match(r"(?:error|fatal|e\d{3,4}\b|f\d{3}\b)", low) else "warning"
        diags.append({"file": rel.replace("\\", "/"), "line": int(m.group("line")),
                      "col": int(m.groupdict()["col"]) if m.groupdict().get("col") else None, "severity": sev, "message": msg[:400]})
    return diags


def in_ranges(line: int, rngs: list[list[int]], slack: int = 2) -> bool:
    return any(a - slack <= line <= b + slack for a, b in rngs)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", help="manifest.json from collect.py (default: .git/codereview-ops/manifest.json)")
    ap.add_argument("--all-lines", action="store_true", help="keep diagnostics outside the changed lines")
    ap.add_argument("--only", help="comma-separated linter names to run")
    ap.add_argument("--skip-slow", action="store_true", help="skip whole-project linters such as clippy")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    mpath = Path(args.manifest) if args.manifest else None
    if mpath is None:
        gd = subprocess.run(["git", "rev-parse", "--absolute-git-dir"], capture_output=True, text=True).stdout.strip()
        mpath = Path(gd) / "codereview-ops" / "manifest.json" if gd else None
    if not mpath or not mpath.is_file():
        print("error: manifest not found; run collect.py first", file=sys.stderr)
        return 2
    m = json.loads(mpath.read_text())
    root = Path(m["root"])
    cfg = m.get("config", {}).get("linters", {})
    if cfg.get("enabled") is False:
        print("linters disabled in config")
        return 0
    disabled = set(cfg.get("disable") or [])
    timeout = int(cfg.get("timeout") or 120)
    only = set(args.only.split(",")) if args.only else None

    files = [f for f in m["files"] if f.get("on_disk")]
    by_lang: dict[str, list[dict]] = {}
    for f in files:
        by_lang.setdefault(f["language"], []).append(f)
    ranges_by_file = {f["path"]: f["changed_ranges"] for f in files}

    ran, missing, results, errors = [], [], [], []
    ran_names: set[str] = set()
    for lint in LINTERS:
        name = lint["name"]
        if name in disabled or (only and name not in only):
            continue
        targets = [f for lang in lint["langs"] for f in by_lang.get(lang, [])]
        if not targets:
            continue
        if lint.get("fallback_for") and lint["fallback_for"] in ran_names:
            continue
        if lint.get("needs_any") and not any((root / n).exists() for n in lint["needs_any"]):
            continue
        if lint.get("slow") and args.skip_slow:
            continue
        exe = resolve(lint["cmd"][0], root)
        if not exe:
            if not lint.get("fallback_for"):
                missing.append(name)
            continue
        paths = [t["path"] for t in targets]
        pkgdirs = sorted({"./" + str(Path(p).parent).replace("\\", "/") for p in paths})
        invocations: list[list[str]] = []
        if lint.get("per_file"):
            for p in paths:
                invocations.append([exe] + [p if a == "{file}" else a for a in lint["cmd"][1:]])
        else:
            argv_: list[str] = [exe]
            for a in lint["cmd"][1:]:
                if a == "{files}":
                    argv_ += paths
                elif a == "{pkgdirs}":
                    argv_ += pkgdirs
                else:
                    argv_.append(a)
            invocations.append(argv_)
        out_text = ""
        for inv in invocations:
            try:
                proc = subprocess.run(inv, cwd=root, capture_output=True, text=True, errors="replace", timeout=timeout)
                out_text += proc.stdout + "\n" + proc.stderr + "\n"
            except subprocess.TimeoutExpired:
                errors.append(f"{name}: timed out after {timeout}s")
            except OSError as e:
                errors.append(f"{name}: {e}")
        diags = parse(out_text, root)
        kept = []
        for d in diags:
            if d["file"] not in ranges_by_file:
                continue  # diagnostics in files outside the review scope
            if not args.all_lines and not in_ranges(d["line"], ranges_by_file[d["file"]]):
                continue
            d["linter"] = name
            kept.append(d)
        ran.append({"linter": name, "files": len(paths), "diagnostics": len(diags), "in_scope": len(kept)})
        ran_names.add(name)
        results += kept

    report = {"ran": ran, "missing": missing, "errors": errors, "diagnostics": results}
    out = Path(m["workdir"]) / "lint.json"
    out.write_text(json.dumps(report, indent=2))
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    print("linters run: " + (", ".join(f"{r['linter']} ({r['in_scope']}/{r['diagnostics']} in scope)" for r in ran) or "none"))
    if missing:
        print("not installed (no evidence from these): " + ", ".join(missing))
    for e in errors:
        print("error: " + e)
    for d in results[:150]:
        col = f":{d['col']}" if d["col"] else ""
        print(f"  [{d['linter']}] {d['file']}:{d['line']}{col} {d['severity']}: {d['message']}")
    if len(results) > 150:
        print(f"  … {len(results) - 150} more in {out}")
    print(f"lint results: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
