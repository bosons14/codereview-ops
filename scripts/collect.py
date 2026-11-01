#!/usr/bin/env python3
"""codereview-ops: work out WHAT to review, in any language.

Resolves the review scope (git diff, staged changes, a commit range, a PR patch, explicit paths or the
whole repository), detects the language of every file, drops generated/vendored/binary files, scans
added lines for secrets, flags risk signals, detects the project's build/test/lint tooling and splits
the work into batches that parallel reviewer agents can take.

Writes  <workdir>/manifest.json  and  <workdir>/diff.patch  and prints a concise summary.
<workdir> defaults to .git/codereview-ops/ inside a git repo (never pollutes the working tree).

Examples:
  collect.py                         # auto: branch vs base + uncommitted, else last commit
  collect.py --base origin/main      # everything since merging off origin/main (+ uncommitted)
  collect.py --staged                # only what is staged
  collect.py --range HEAD~3..HEAD    # a commit range
  collect.py --diff-file pr.patch    # a patch from `gh pr diff` or elsewhere
  collect.py --paths src/ lib/x.rs   # full-file review of these paths
  collect.py --all                   # full-repo audit
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from languages import (DEFAULT_IGNORE, detect_language, family, is_binary,  # noqa: E402
                       looks_generated, matches_any)
from secrets_scan import scan_text  # noqa: E402

CONFIG_NAMES = (".codereview-ops.json", ".codereview-ops/config.json")
RULE_FILES = ("CODEREVIEW.md", ".codereview-ops/rules.md", "REVIEW_GUIDELINES.md", ".github/CODEREVIEW.md")
CONTEXT_FILES = ("CLAUDE.md", "AGENTS.md", "CONTRIBUTING.md", ".editorconfig", "SECURITY.md")

DEFAULT_CONFIG = {
    "base": None,
    "ignore": [],
    "include_generated": False,
    "min_severity": "nit",          # lowest severity to report: blocker|major|minor|nit
    "fail_on": "blocker",           # report.py exit code threshold
    "max_findings": 60,
    "focus": [],                    # e.g. ["security", "correctness"]
    "batch_lines": 700,             # changed lines per reviewer batch
    "batch_files": 12,
    "max_file_lines": 4000,         # above this, full-file mode reviews changed regions/hotspots only
    "linters": {"enabled": True, "disable": [], "timeout": 120},
    "rules_file": None,
}

RISK_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("exec", re.compile(r"\b(?:eval|exec|system|popen|spawn|execSync|Runtime\.getRuntime|ProcessBuilder|os\.system|subprocess|shell\s*=\s*True|child_process|backticks?|`[^`]*\$\()", re.I)),
    ("sql", re.compile(r"\b(?:SELECT\s.+\sFROM|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|executeQuery|raw\(|\.query\(|cursor\.execute)", re.I)),
    ("deserialize", re.compile(r"\b(?:pickle\.loads?|yaml\.load\(|unserialize|Marshal\.load|ObjectInputStream|BinaryFormatter|readObject|jsonpickle|torch\.load)", re.I)),
    ("html-injection", re.compile(r"(?:innerHTML|outerHTML|dangerouslySetInnerHTML|v-html|\|\s*safe\b|mark_safe|html_safe|document\.write)")),
    ("crypto", re.compile(r"\b(?:md5|sha1|DES|RC4|ECB|Math\.random|rand\(\)|random\.random|SecureRandom|crypto|cipher|hmac|bcrypt|scrypt|argon2|pbkdf2|verify=False|InsecureSkipVerify|rejectUnauthorized\s*:\s*false)\b", re.I)),
    ("authz", re.compile(r"\b(?:auth|login|logout|session|cookie|jwt|oauth|permission|role|is_?admin|acl|csrf|cors|password|token)\w*", re.I)),
    ("filesystem", re.compile(r"(?:\.\./|path\.join|os\.path\.join|open\(|fopen|readFile|writeFile|unlink|rmtree|chmod|chown|tempfile|mktemp|send_?file|zipfile|tarfile|extractall)", re.I)),
    ("network", re.compile(r"\b(?:requests\.(?:get|post)|fetch\(|axios|http\.Get|urlopen|HttpClient|curl_|socket|redirect|url_for|webhook)", re.I)),
    ("memory-unsafe", re.compile(r"\b(?:strcpy|strcat|sprintf|gets|memcpy|memmove|alloca|malloc|realloc|free|reinterpret_cast|unsafe|transmute|from_raw|as_ptr|__syncthreads|atomicAdd|volatile)\b")),
    ("concurrency", re.compile(r"\b(?:thread|mutex|lock|async|await|goroutine|go\s+func|chan\b|Promise\.all|synchronized|atomic|semaphore|race|spawn|tokio|asyncio|ThreadPool|Executor)\w*", re.I)),
    ("migration", re.compile(r"\b(?:ALTER\s+TABLE|DROP\s+(?:TABLE|COLUMN|INDEX)|CREATE\s+INDEX|migrat\w*|add_column|remove_column)", re.I)),
]

TEST_PATH = re.compile(r"(?:^|/)(?:tests?|spec|specs|__tests__|testing|testbench|tb)(?:/|$)|(?:^|/)test_[^/]+$|_test\.[a-z]+$|\.test\.[a-z]+$|\.spec\.[a-z]+$|Test\.[a-z]+$|Tests?\.[a-z]+$|_tb\.s?v$", re.I)
DEP_MANIFESTS = {"package.json", "requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile",
                 "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "build.gradle.kts", "Gemfile",
                 "composer.json", "mix.exs", "pubspec.yaml", "Package.swift", "*.csproj", "conanfile.txt",
                 "vcpkg.json", "environment.yml", "Dockerfile"}


# --------------------------------------------------------------------------- git helpers

def git(args: list[str], cwd: Path, check: bool = False) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, errors="replace")
    if check and proc.returncode not in (0, 1):
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout if proc.returncode in (0, 1) else ""


def git_root(start: Path) -> Path | None:
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=start, capture_output=True, text=True)
    return Path(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None


def rev_ok(rev: str, cwd: Path) -> bool:
    return subprocess.run(["git", "rev-parse", "--verify", "--quiet", rev + "^{commit}"], cwd=cwd,
                          capture_output=True).returncode == 0


def detect_base(cwd: Path, configured: str | None) -> str | None:
    cands = [configured] if configured else []
    head = git(["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], cwd).strip()
    if head:
        cands.append(head)
    cands += ["origin/main", "origin/master", "main", "master", "origin/develop", "develop", "trunk"]
    for c in cands:
        if c and rev_ok(c, cwd):
            return c
    return None


def untracked(cwd: Path) -> list[str]:
    return [l for l in git(["ls-files", "--others", "--exclude-standard", "-z"], cwd).split("\0") if l]


def is_dirty(cwd: Path) -> bool:
    return bool(git(["status", "--porcelain", "--untracked-files=normal"], cwd).strip())


# --------------------------------------------------------------------------- diff parsing

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def parse_patch(text: str) -> dict[str, dict]:
    """Return {new_path: {status, old_path, added, removed, lines:set(new-side changed lines), binary}}."""
    files: dict[str, dict] = {}
    cur: dict | None = None
    new_line = 0
    for raw in text.splitlines():
        if raw.startswith("diff --git "):
            m = re.match(r'^diff --git "?a/(.+?)"? "?b/(.+?)"?$', raw)
            a, b = (m.group(1), m.group(2)) if m else ("", "")
            cur = {"status": "M", "old_path": a, "path": b, "added": 0, "removed": 0, "lines": set(), "binary": False}
            files[b] = cur
            continue
        if cur is None:
            continue
        if raw.startswith("new file mode"):
            cur["status"] = "A"
        elif raw.startswith("deleted file mode"):
            cur["status"] = "D"
        elif raw.startswith("rename from "):
            cur["status"] = "R"
            cur["old_path"] = raw[len("rename from "):]
        elif raw.startswith("rename to "):
            newp = raw[len("rename to "):]
            files.pop(cur["path"], None)
            cur["path"] = newp
            files[newp] = cur
        elif raw.startswith("Binary files") or raw.startswith("GIT binary patch"):
            cur["binary"] = True
        elif raw.startswith("+++ "):
            target = raw[4:].strip().strip('"')
            if target != "/dev/null":
                target = target[2:] if target.startswith("b/") else target
                if target != cur["path"]:
                    files.pop(cur["path"], None)
                    cur["path"] = target
                    files[target] = cur
        elif raw.startswith("--- "):
            pass
        elif raw.startswith("@@"):
            m = HUNK.match(raw)
            if m:
                new_line = int(m.group(3))
        elif raw.startswith("+"):
            cur["added"] += 1
            cur["lines"].add(new_line)
            new_line += 1
        elif raw.startswith("-"):
            cur["removed"] += 1
            # mark the deletion point so reviewers look at the surrounding code
            cur["lines"].add(max(new_line, 1))
        elif raw.startswith(" "):
            new_line += 1
    return files


def added_text(patch: str) -> dict[str, list[tuple[int, str]]]:
    """Map path -> [(new_line_no, text)] for added lines only."""
    out: dict[str, list[tuple[int, str]]] = {}
    path = None
    n = 0
    for raw in patch.splitlines():
        if raw.startswith("+++ "):
            t = raw[4:].strip().strip('"')
            path = None if t == "/dev/null" else (t[2:] if t.startswith("b/") else t)
        elif raw.startswith("@@"):
            m = HUNK.match(raw)
            n = int(m.group(3)) if m else 0
        elif path and raw.startswith("+") and not raw.startswith("+++"):
            out.setdefault(path, []).append((n, raw[1:]))
            n += 1
        elif raw.startswith(" "):
            n += 1
    return out


def ranges(lines: set[int]) -> list[list[int]]:
    out: list[list[int]] = []
    for n in sorted(lines):
        if out and n <= out[-1][1] + 1:
            out[-1][1] = n
        else:
            out.append([n, n])
    return out


# --------------------------------------------------------------------------- project detection

def detect_project(root: Path) -> dict:
    found = {p.name for p in root.iterdir()} if root.is_dir() else set()
    eco, tests, lints = [], [], []

    def has(name: str) -> bool:
        return name in found

    if has("package.json"):
        eco.append("node")
        try:
            pkg = json.loads((root / "package.json").read_text())
            scripts = pkg.get("scripts", {})
            runner = "pnpm" if has("pnpm-lock.yaml") else "yarn" if has("yarn.lock") else "bun" if has("bun.lockb") else "npm"
            for key in ("test", "test:unit"):
                if key in scripts:
                    tests.append(f"{runner} run {key}")
                    break
            for key in ("lint", "typecheck", "check"):
                if key in scripts:
                    lints.append(f"{runner} run {key}")
        except (OSError, ValueError):
            pass
    if has("pyproject.toml") or has("setup.py") or has("setup.cfg") or has("requirements.txt"):
        eco.append("python")
        if has("tests") or has("test") or has("pytest.ini") or has("conftest.py") or has("tox.ini"):
            tests.append("python -m pytest -q")
    if has("Cargo.toml"):
        eco.append("rust"); tests.append("cargo test"); lints.append("cargo clippy --all-targets")
    if has("go.mod"):
        eco.append("go"); tests.append("go test ./..."); lints.append("go vet ./...")
    if has("pom.xml"):
        eco.append("maven"); tests.append("mvn -q test")
    if has("build.gradle") or has("build.gradle.kts"):
        eco.append("gradle"); tests.append("./gradlew test" if has("gradlew") else "gradle test")
    if has("Gemfile"):
        eco.append("ruby"); tests.append("bundle exec rspec" if has("spec") else "bundle exec rake test")
    if has("composer.json"):
        eco.append("php"); tests.append("vendor/bin/phpunit")
    if has("mix.exs"):
        eco.append("elixir"); tests.append("mix test")
    if has("pubspec.yaml"):
        eco.append("dart"); tests.append("dart test")
    if has("Package.swift"):
        eco.append("swift"); tests.append("swift test")
    if has("build.zig"):
        eco.append("zig"); tests.append("zig build test")
    if any(n.endswith((".sln", ".csproj", ".fsproj")) for n in found):
        eco.append("dotnet"); tests.append("dotnet test")
    if has("CMakeLists.txt"):
        eco.append("cmake"); tests.append("ctest --test-dir build")
    if has("Makefile") or has("makefile") or has("GNUmakefile"):
        eco.append("make")
        try:
            mk = (root / ("Makefile" if has("Makefile") else "makefile" if has("makefile") else "GNUmakefile")).read_text(errors="replace")
            if re.search(r"^test\s*:", mk, re.M):
                tests.append("make test")
            if re.search(r"^lint\s*:", mk, re.M):
                lints.append("make lint")
        except OSError:
            pass
    if has("deno.json") or has("deno.jsonc"):
        eco.append("deno"); tests.append("deno test")

    ci = [str(p.relative_to(root)) for pat in (".github/workflows/*.yml", ".github/workflows/*.yaml", ".gitlab-ci.yml",
                                                ".circleci/config.yml", "Jenkinsfile", "azure-pipelines.yml",
                                                ".buildkite/*.yml") for p in root.glob(pat)]
    return {"ecosystems": eco, "test_commands": tests, "lint_commands": lints, "ci": ci}


def load_config(root: Path) -> tuple[dict, str | None]:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    for name in CONFIG_NAMES:
        p = root / name
        if p.is_file():
            try:
                user = json.loads(p.read_text())
            except ValueError as e:
                print(f"warning: ignoring invalid {name}: {e}", file=sys.stderr)
                return cfg, None
            for k, v in user.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
            return cfg, name
    return cfg, None


# --------------------------------------------------------------------------- main

def walk_files(root: Path, paths: list[str], in_git: bool) -> list[str]:
    out: list[str] = []
    if in_git and not paths:
        return [l for l in git(["ls-files", "-z"], root).split("\0") if l]
    targets = [Path(p) for p in paths] if paths else [root]
    for t in targets:
        t = t if t.is_absolute() else (Path.cwd() / t)
        if t.is_file():
            out.append(os.path.relpath(t, root))
        elif t.is_dir():
            if in_git:
                rel = os.path.relpath(t, root)
                out += [l for l in git(["ls-files", "-z", "--", rel], root).split("\0") if l]
                out += [l for l in git(["ls-files", "--others", "--exclude-standard", "-z", "--", rel], root).split("\0") if l]
            else:
                for dp, dns, fns in os.walk(t):
                    dns[:] = [d for d in dns if not d.startswith(".") and d not in {"node_modules", "__pycache__", "venv", ".venv", "target", "dist", "build"}]
                    out += [os.path.relpath(Path(dp) / f, root) for f in fns]
        else:
            print(f"warning: {t} not found", file=sys.stderr)
    return sorted(set(out))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--base", help="review everything since merge-base with this ref (+ uncommitted)")
    g.add_argument("--staged", action="store_true", help="review staged changes only")
    g.add_argument("--range", dest="rev_range", help="review a commit range, e.g. HEAD~3..HEAD or a single SHA")
    g.add_argument("--diff-file", help="review a unified diff/patch file")
    g.add_argument("--paths", nargs="+", help="full-file review of these files/directories")
    g.add_argument("--all", action="store_true", help="full-repository audit")
    ap.add_argument("--root", default=".", help="repository/project root (default: cwd)")
    ap.add_argument("--workdir", help="where to write manifest.json and diff.patch")
    ap.add_argument("--include-generated", action="store_true")
    ap.add_argument("--json", action="store_true", help="print the full manifest JSON instead of a summary")
    args = ap.parse_args(argv)

    start = Path(args.root).resolve()
    groot = git_root(start)
    in_git = groot is not None
    root = groot or start
    cfg, cfg_name = load_config(root)
    include_generated = args.include_generated or cfg.get("include_generated")
    ignore = DEFAULT_IGNORE + list(cfg.get("ignore") or [])

    patch = ""
    full_mode = False
    file_list: list[str] = []
    scope = ""
    base_used = None

    if args.diff_file:
        patch = Path(args.diff_file).read_text(errors="replace")
        scope = f"patch file {args.diff_file}"
    elif args.paths or args.all or not in_git:
        full_mode = True
        file_list = walk_files(root, args.paths or [], in_git)
        scope = ("paths: " + ", ".join(args.paths)) if args.paths else "entire repository" if in_git else "entire directory (not a git repo)"
    elif args.staged:
        patch = git(["diff", "--cached", "--no-color", "--no-ext-diff", "-M", "-U3"], root)
        scope = "staged changes"
    elif args.rev_range:
        rr = args.rev_range if ".." in args.rev_range else f"{args.rev_range}~1..{args.rev_range}"
        if ".." not in args.rev_range and not rev_ok(args.rev_range + "~1", root):
            patch = git(["show", "--format=", "--no-color", "--no-ext-diff", "-M", "-U3", args.rev_range], root)
        else:
            patch = git(["diff", "--no-color", "--no-ext-diff", "-M", "-U3", rr], root)
        scope = f"commit range {rr}"
    else:
        base = args.base or detect_base(root, cfg.get("base"))
        if args.base and not rev_ok(args.base, root):
            print(f"error: base ref '{args.base}' not found (try `git fetch`?)", file=sys.stderr)
            return 2
        mb = git(["merge-base", base, "HEAD"], root).strip() if base else ""
        head = git(["rev-parse", "HEAD"], root).strip()
        if mb and mb != head:
            patch = git(["diff", "--no-color", "--no-ext-diff", "-M", "-U3", mb], root)
            scope = f"branch changes since {base} (merge-base {mb[:10]}) + uncommitted"
            base_used = base
        elif is_dirty(root):
            patch = git(["diff", "HEAD", "--no-color", "--no-ext-diff", "-M", "-U3"], root) if head else \
                git(["diff", "--cached", "--no-color", "--no-ext-diff", "-U3"], root)
            scope = "uncommitted changes vs HEAD"
        elif head and rev_ok("HEAD~1", root):
            patch = git(["diff", "--no-color", "--no-ext-diff", "-M", "-U3", "HEAD~1..HEAD"], root)
            scope = "last commit (HEAD~1..HEAD)"
        elif head:
            patch = git(["show", "--format=", "--no-color", "--no-ext-diff", "-U3", "HEAD"], root)
            scope = "initial commit"
        if "uncommitted" in scope:  # working-tree comparisons also cover new, untracked files
            for u in untracked(root):
                try:
                    if (root / u).stat().st_size > 2_000_000:
                        continue
                except OSError:
                    continue
                patch += git(["diff", "--no-index", "--no-color", "--", "/dev/null", u], root)

    files: list[dict] = []
    skipped: list[dict] = []
    secrets: list[dict] = []
    if full_mode:
        entries = {f: None for f in file_list}
        adds: dict[str, list[tuple[int, str]]] = {}
    else:
        entries = parse_patch(patch)
        adds = added_text(patch)

    for path, info in entries.items():
        abs_p = root / path
        status = info["status"] if info else "F"
        if status == "D":
            skipped.append({"path": path, "reason": "deleted"})
            continue
        try:
            sample = abs_p.read_bytes()[:65536] if abs_p.is_file() else b""
        except OSError:
            sample = b""
        if (info and info.get("binary")) or is_binary(path, sample):
            skipped.append({"path": path, "reason": "binary"})
            continue
        if matches_any(path, ignore):
            skipped.append({"path": path, "reason": "ignored (vendored/lockfile/config ignore)"})
            continue
        head = sample.decode("utf-8", errors="replace")
        if not include_generated and looks_generated(head):
            skipped.append({"path": path, "reason": "generated"})
            continue
        try:
            text = abs_p.read_text(errors="replace") if abs_p.is_file() else ""
        except OSError:
            text = ""
        nlines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
        lang = detect_language(path, head)
        if full_mode:
            changed = set(range(1, nlines + 1))
            added_lines = list(enumerate(text.splitlines(), 1))
            add_n, rem_n = nlines, 0
        else:
            changed = info["lines"]
            added_lines = adds.get(path, [])
            add_n, rem_n = info["added"], info["removed"]
        # secrets on added lines only
        only = {n for n, _ in added_lines}
        if text and only:
            secrets += scan_text(text, path, only)
        elif added_lines and not text:  # patch-only review (file not on disk)
            for n, line in added_lines:
                secrets += [dict(h, line=n) for h in scan_text(line, path)]
        joined = "\n".join(l for _, l in added_lines)
        risks = sorted({tag for tag, rx in RISK_PATTERNS if rx.search(joined)})
        name = Path(path).name
        entry = {
            "path": path,
            "status": status,
            "old_path": info["old_path"] if info and info["status"] == "R" else None,
            "language": lang,
            "family": family(lang),
            "lines_total": nlines,
            "added": add_n,
            "removed": rem_n,
            "changed_ranges": ranges(changed) if not full_mode else [[1, nlines]] if nlines else [],
            "is_test": bool(TEST_PATH.search(path)),
            "is_dependency_manifest": matches_any(name, list(DEP_MANIFESTS)),
            "risk_tags": risks,
            "on_disk": abs_p.is_file(),
            "large": nlines > int(cfg["max_file_lines"]),
        }
        files.append(entry)

    # language summary
    langs: dict[str, dict] = {}
    for f in files:
        d = langs.setdefault(f["language"], {"files": 0, "changed_lines": 0})
        d["files"] += 1
        d["changed_lines"] += f["added"] + f["removed"]

    # batches: group by top-level dir, fill up to budget
    budget, max_files = int(cfg["batch_lines"]), int(cfg["batch_files"])
    weight = lambda f: max(1, min(f["added"] + f["removed"], int(cfg["max_file_lines"])))  # noqa: E731
    ordered = sorted(files, key=lambda f: (str(Path(f["path"]).parent), f["is_test"], f["path"]))
    batches: list[dict] = []
    cur: list[dict] = []
    cur_w = 0
    for f in ordered:
        w = weight(f)
        if cur and (cur_w + w > budget or len(cur) >= max_files):
            batches.append({"files": [x["path"] for x in cur], "weight": cur_w})
            cur, cur_w = [], 0
        cur.append(f)
        cur_w += w
    if cur:
        batches.append({"files": [x["path"] for x in cur], "weight": cur_w})
    for i, b in enumerate(batches, 1):
        b["id"] = i
        b["languages"] = sorted({f["language"] for f in files if f["path"] in b["files"]})
        b["risk_tags"] = sorted({t for f in files if f["path"] in b["files"] for t in f["risk_tags"]})

    src_changed = [f for f in files if not f["is_test"] and f["family"] not in {"config", "other"} and f["language"] not in {"Markdown", "Text", "JSON"}]
    tests_changed = [f for f in files if f["is_test"]]
    rules_file = cfg.get("rules_file")
    rule_files = [r for r in ([rules_file] if rules_file else []) + list(RULE_FILES) if r and (root / r).is_file()]
    context_files = [c for c in CONTEXT_FILES if (root / c).is_file()]

    total_changed = sum(f["added"] + f["removed"] for f in files)
    size = "small" if total_changed <= 300 and len(files) <= 8 else "medium" if total_changed <= 1500 else "large"

    manifest = {
        "tool": "codereview-ops",
        "root": str(root),
        "git": in_git,
        "scope": scope or "nothing to review",
        "base": base_used,
        "mode": "full-file" if full_mode else "diff",
        "size": size,
        "totals": {"files": len(files), "skipped": len(skipped), "changed_lines": total_changed,
                   "languages": len(langs), "batches": len(batches)},
        "languages": dict(sorted(langs.items(), key=lambda kv: -kv[1]["changed_lines"])),
        "files": files,
        "skipped": skipped,
        "batches": batches,
        "secrets": secrets,
        "signals": {
            "source_changed_without_tests": bool(src_changed) and not tests_changed and not full_mode,
            "dependency_manifests_changed": [f["path"] for f in files if f["is_dependency_manifest"]],
            "risk_tags": sorted({t for f in files for t in f["risk_tags"]}),
            "large_files": [f["path"] for f in files if f["large"]],
        },
        "project": detect_project(root),
        "config": cfg,
        "config_file": cfg_name,
        "rule_files": rule_files,
        "context_files": context_files,
    }

    if args.workdir:
        workdir = Path(args.workdir)
    elif in_git:
        gd = git(["rev-parse", "--absolute-git-dir"], root).strip()
        workdir = Path(gd) / "codereview-ops"
    else:
        workdir = Path(tempfile.gettempdir()) / ("codereview-ops-" + hashlib.sha1(str(root).encode()).hexdigest()[:10])
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "diff.patch").write_text(patch)
    manifest["workdir"] = str(workdir)
    manifest["diff_file"] = str(workdir / "diff.patch") if patch else None
    (workdir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    if args.json:
        print(json.dumps(manifest, indent=2))
        return 0
    print(summary(manifest))
    return 0


def summary(m: dict) -> str:
    t = m["totals"]
    out = [f"codereview-ops scope: {m['scope']}",
           f"mode={m['mode']}  size={m['size']}  files={t['files']}  changed_lines={t['changed_lines']}  "
           f"skipped={t['skipped']}  batches={t['batches']}",
           "languages: " + (", ".join(f"{k} ({v['files']})" for k, v in m["languages"].items()) or "-")]
    p = m["project"]
    out.append("project: ecosystems=" + (",".join(p["ecosystems"]) or "-") +
               "  tests=" + (" | ".join(p["test_commands"]) or "-") +
               "  lint=" + (" | ".join(p["lint_commands"]) or "-"))
    if m["rule_files"] or m["context_files"] or m["config_file"]:
        out.append("read first: " + ", ".join(filter(None, [m["config_file"], *m["rule_files"], *m["context_files"]])))
    s = m["signals"]
    flags = []
    if m["secrets"]:
        flags.append(f"SECRETS={len(m['secrets'])}")
    if s["source_changed_without_tests"]:
        flags.append("no-tests-changed")
    if s["dependency_manifests_changed"]:
        flags.append("deps:" + ",".join(s["dependency_manifests_changed"]))
    if s["risk_tags"]:
        flags.append("risk:" + ",".join(s["risk_tags"]))
    if s["large_files"]:
        flags.append("large:" + ",".join(s["large_files"][:5]))
    out.append("signals: " + (" ".join(flags) or "none"))
    for sec in m["secrets"][:20]:
        out.append(f"  secret {sec['file']}:{sec['line']} {sec['title']} [{sec['match']}]")
    out.append("files:")
    for f in m["files"][:200]:
        rng = ",".join(f"{a}-{b}" if a != b else str(a) for a, b in f["changed_ranges"][:8])
        if len(f["changed_ranges"]) > 8:
            rng += ",…"
        tags = (" [" + ",".join(f["risk_tags"]) + "]") if f["risk_tags"] else ""
        test = " (test)" if f["is_test"] else ""
        out.append(f"  {f['status']} {f['path']}  {f['language']}  +{f['added']}/-{f['removed']}  lines {rng}{test}{tags}")
    if len(m["files"]) > 200:
        out.append(f"  … {len(m['files']) - 200} more in manifest.json")
    if m["skipped"]:
        out.append("skipped: " + ", ".join(f"{s['path']} ({s['reason']})" for s in m["skipped"][:15]) +
                   (" …" if len(m["skipped"]) > 15 else ""))
    out.append("batches: " + "; ".join(f"#{b['id']} {len(b['files'])} files ~{b['weight']} lines" for b in m["batches"][:20]))
    out.append(f"manifest: {m['workdir']}/manifest.json" + (f"   diff: {m['diff_file']}" if m["diff_file"] else ""))
    return "\n".join(out)


if __name__ == "__main__":
    sys.exit(main())
