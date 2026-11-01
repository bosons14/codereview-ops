# Code review — **REQUEST CHANGES**

_Scope: branch changes since main (merge-base f533487a4a) + uncommitted · 4 files · 13 changed lines · Python, TypeScript, Go, Shell_

🔴 1 blocker · 🟠 4 major · 🟡 3 minor · ⚪ 0 nit

Adds load/run helpers and a hard-coded DB password to src/calc.py, a new web render helper (web/app.ts), an empty Go main (web/x.go) and a .txt cleanup loop in scripts/run.sh. Not mergeable as is: it commits a real-looking database password, and every new helper is an injection sink (shell command injection, unsafe pickle deserialization, HTML injection). The run.sh loop was reproduced deleting an unrelated file when a filename contains a space. Note: web/ is untracked (uncommitted), so it is not on the feature branch yet.

## 🔴 Blocker (1)

### 1. Hard-coded database password committed to source
`src/calc.py:2` `security`

DB_PASSWORD = "Xk9#mQ2vLp8zR4tY" is a high-entropy, real-looking credential committed on the feature branch (commit 395a69a). Anyone with repo read access (forks, CI logs, mirrors) gets the password, and it stays in git history even if the line is later deleted. It is also unused in the module, so it serves no purpose here.

**Suggested fix:**

```
Remove the constant, rotate the password, and read it from the environment or a secret store where it is actually needed:
```python
DB_PASSWORD = os.environ["DB_PASSWORD"]
```
```

## 🟠 Major (4)

### 1. Cleanup loop parses ls and deletes the wrong files on spaces
`scripts/run.sh:2` `reliability`

for f in $(ls *.txt); do rm $f; done word-splits filenames. With a file named "a b.txt" next to an unrelated file "a", the loop ran rm a and rm b.txt: it deleted the unrelated file "a" and left "a b.txt" in place. Names with glob characters or a leading dash cause similar damage, and if no .txt files exist ls prints an error into the loop.

**Suggested fix:**

```
Glob directly, quote, and end options:
```bash
for f in ./*.txt; do [ -e "$f" ] && rm -- "$f"; done
```
or simply `rm -f -- ./*.txt`.
```

### 2. load() unpickles arbitrary bytes, enabling code execution
`src/calc.py:5-6` `security` · confidence: medium

pickle.loads executes arbitrary code embedded in the payload (via __reduce__). If blob ever comes from a network request, upload, cache or DB row an attacker can write, calling load(blob) runs attacker code in the process. Nothing in the signature or name warns callers that blob must be trusted. Confidence is medium because no callers exist yet to show where blob comes from.

**Suggested fix:**

```
Use a data-only format for anything not fully trusted:
```python
import json

def load(blob):
    return json.loads(blob)
```
If pickle is truly required, restrict it to trusted data and say so in the name/docstring, or verify an HMAC over the blob before loading.
```

### 3. run() passes its argument to a shell, allowing command injection
`src/calc.py:7-8` `security`

os.system("ls " + cmd) runs the string through /bin/sh, so any shell metacharacters in cmd execute arbitrary commands: run('; echo INJECTED') printed INJECTED. Any caller passing user or file-derived input gets remote code execution. The name is also misleading: it does not run cmd, it lists a path, and os.system's exit status is discarded so failures are silent. No callers exist yet, so reachability depends on future use (severity would be blocker once fed request input).

**Suggested fix:**

```
Avoid the shell and pass the path as an argument:
```python
def run(path):
    subprocess.run(["ls", "--", path], check=True)
```
```

### 4. render() writes unescaped name into innerHTML (XSS)
`web/app.ts:2` `security`

el.innerHTML = "<b>" + name + "</b>" parses name as HTML. A name such as <img src=x onerror=alert(document.cookie)> executes script in the page, which is a stored or reflected XSS for any user-controlled name (profile names, query params).

**Suggested fix:**

```
Build the element and set text, not HTML:
```ts
export function render(el: HTMLElement, name: string) {
  const b = document.createElement("b");
  b.textContent = name;
  el.replaceChildren(b);
}
```
```

## 🟡 Minor (3)

### 1. New helpers ship with no tests
`src/calc.py:5` `tests`

load, run and render are new public functions with security-sensitive behaviour, but no tests were added (the repo has no tests at all; package.json runs jest). Reverting any of them would not fail CI, and nothing pins the escaping or argument-handling behaviour once fixed.

**Suggested fix:**

Add tests for the fixed behaviour, e.g. that render() leaves '<script>' as literal text and that run() treats '; echo x' as a single path argument.

### 2. Remove AWS access key ID constant from client code
`web/app.ts:4` `security`

const key = "AKIAIOSFODNN7EXAMPLE" is the documented AWS example key, so this is probably not a live credential, which is why it is minor. It is still unused and unexported, it trips secret scanners, and it shows a pattern of putting AWS keys in browser code. A real key here would ship to every browser in the bundle and would be a blocker.

**Suggested fix:**

Delete the line. If AWS access is needed, call it from the server or use short-lived credentials (e.g. Cognito/STS), never a static key in frontend code.

### 3. Stray empty Go main package not covered by the stated intent
`web/x.go:1-2` `maintainability` · confidence: medium

The intent covers calc helpers and a web render helper. web/x.go adds an empty package main with no go.mod, next to TypeScript sources. It does nothing and looks like leftover scaffolding. It will confuse Go tooling (go vet/build from the root has no module) and anyone reading the web/ directory.

**Suggested fix:**

Drop web/x.go from the change, or explain in the PR why it is needed and add a go.mod.

## Evidence

- collect.py secret scan (2 hits, both reported)
- ruff (1 in scope: I001 import order, discarded as style nit)
- repro: scripts/run.sh in scratch dir (wrong file deleted)
- repro: calc.run command injection
- grep for callers of add/load/run/render (none found)

## Not checked

- shellcheck not installed
- npm test (jest) not run: no test files exist
- tsc/go build not run: no tsconfig.json or go.mod in repo

<sub>Generated by codereview-ops</sub>