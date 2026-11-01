# Pitfalls by language family

The manifest gives each file a `family`. Read the sections for the families in scope. Language
names not listed still get the universal checklist. Reason from first principles about the
language's type system, memory model, concurrency model and standard library sharp edges.

## native: C, C++, CUDA, HIP, OpenCL, Rust, Zig, assembly
- Memory safety: bounds on every index/copy, `strcpy/sprintf/gets`, length arithmetic overflow
  before allocation, use-after-free, double free, dangling references to temporaries / moved-from
  objects, iterator invalidation after container mutation.
- Undefined behaviour: signed overflow, shifts ≥ width, strict aliasing, uninitialised reads,
  data races, null deref, misaligned access.
- C++: rule of 0/3/5, `std::move` then use, exceptions crossing C boundaries, `noexcept` lies,
  implicit conversions, `auto` copying when a reference was meant.
- Rust: `unsafe` blocks must state and uphold invariants; `unwrap()/expect()` on fallible input;
  `as` casts truncating; `Send/Sync` assumptions; blocking inside async; lock guards held across `.await`.
- CUDA/GPU: missing `__syncthreads()` between shared-memory write and read, sync inside divergent
  branches (deadlock), race on shared/global memory without atomics, out-of-range thread index
  guard, uncoalesced access, bank conflicts, unchecked API errors (`cudaGetLastError` after launch),
  host/device pointer confusion, stream ordering assumptions, integer overflow in `blockIdx*blockDim`.
- Build: new warnings suppressed, ABI changes in public headers, macros with side effects.

## managed: Go, Java, Kotlin, Scala, C#, F#, Swift, Dart
- Go: ignored `err`, `defer` in loops, loop-variable capture in goroutines (pre-1.22), nil map
  writes, nil interface vs typed nil, unbuffered channel deadlocks, goroutine leaks without
  cancellation, `context` not propagated, slices aliasing the same backing array after `append`.
- Java/Kotlin/Scala: `equals`/`hashCode` contract, mutable static state, `Optional.get()`,
  resources without try-with-resources/`use`, checked exceptions wrapped and lost, `!!` in Kotlin,
  coroutine scope leaks, `synchronized` on the wrong monitor, streams with side effects.
- C#: `async void`, `.Result`/`.Wait()` deadlocks, `IDisposable` not disposed, LINQ multiple
  enumeration, culture-sensitive string comparisons.
- Swift: force unwraps/`try!`, retain cycles in closures (`[weak self]`), main-thread UI rules.
- Integer overflow and `float`/`double` money arithmetic (use decimal types).

## dynamic: Python, JavaScript, TypeScript, Ruby, PHP, Perl, Lua, Elixir, R, Julia
- Python: mutable default args, late-binding closures in loops, broad `except:`, `is` vs `==`,
  `pickle`/`yaml.load`/`eval` on untrusted data, `subprocess(shell=True)`, timezone-naive datetimes,
  float equality, generators consumed twice, blocking calls in `async def`.
- JS/TS: `==` vs `===`, `any`/non-null `!` hiding real nulls, un-awaited promises, `forEach` with
  async callbacks, prototype pollution via object merge, `innerHTML`/`dangerouslySetInnerHTML`,
  `parseInt` without radix, number precision > 2^53, `this` binding, mutating props/state (React
  stale closures, missing effect deps).
- Ruby: `send`/`constantize` with user input, mass assignment, N+1 in ActiveRecord, `rescue => e`
  swallowing.
- PHP: loose comparison (`==` type juggling), `include` with user input, `unserialize`, SQL string concat.
- Data science (Python/R/Julia): train/test leakage, silent broadcasting, chained assignment,
  in-place mutation of shared frames, random seeds, NaN propagation, dtype downcasting.

## shell: sh, bash, zsh, PowerShell, batch
- Unquoted variables (word splitting, globbing), `$(ls)` loops, missing `set -euo pipefail` (or
  conscious handling), `cd` without failure check, `rm -rf "$VAR/"` with empty VAR, `eval`,
  temporary files without `mktemp`, parsing `ls`/`ps` output, bashisms under `#!/bin/sh`, secrets in
  command lines (visible in `ps`). PowerShell: `Invoke-Expression`, missing `-ErrorAction Stop`.

## query: SQL, GraphQL, ORMs
- String-built queries; dynamic identifiers not allow-listed. Missing `WHERE` on UPDATE/DELETE.
- NULL semantics (`= NULL`, `NOT IN` with NULLs), implicit casts defeating indexes, transaction
  isolation assumptions, long-held locks in migrations, non-reversible migrations.
- GraphQL: unbounded depth/complexity, per-field authorization, N+1 resolvers.

## hdl: Verilog, SystemVerilog, VHDL, SDC/XDC/Tcl
- Clock-domain crossings without synchronisers (multi-bit buses need gray code/handshake/async FIFO).
- Latches from incomplete `if`/`case` in combinational blocks; blocking vs non-blocking misuse;
  sim/synth mismatch (`initial`, delays, `x` assignments, sensitivity lists).
- Reset: async assert/sync de-assert, polarity consistency, reset synchroniser per domain.
- Width/sign: truncation, sign extension, unsized literals; FSM illegal-state recovery.
- Constraints: missing generated clocks, false paths hiding real paths, unconstrained I/O.
- If the `eda-ops` plugin is installed, use its `rtl-review` / `sdc-review` skills for depth.

## infra / config / build: Dockerfile, Terraform/HCL, Kubernetes YAML, CI, Nix, Make, CMake, Bazel
- Docker: `latest` tags, running as root, secrets in `ENV`/`ARG`/layers, `curl | sh`, missing
  `--no-install-recommends`/cache cleanup, `ADD` with remote URLs.
- Terraform/K8s: public exposure, wildcard IAM, missing encryption/backups, `privileged: true`,
  no resource limits, `hostPath`, secrets in plain manifests, `prevent_destroy` absent on stateful resources.
- CI: `pull_request_target` + checkout of PR head, untrusted `${{ github.event.* }}` interpolated
  into `run:`, unpinned third-party actions, over-broad `permissions`.
- Build files: non-hermetic downloads, unpinned versions, flags that disable warnings or security
  hardening, targets that silently skip tests.

## contract: Solidity, Vyper, Move, Cairo
- Reentrancy (checks-effects-interactions), access control on privileged functions, unchecked
  external call return values, integer over/underflow (pre-0.8 or `unchecked`), front-running/MEV,
  oracle manipulation, `tx.origin` auth, upgradeable-proxy storage collisions, DoS via unbounded loops.

## docs / text: Markdown, reStructuredText, comments
- Only review for correctness against the code (wrong commands, outdated flags, broken links to
  changed paths) and for leaked secrets/internal URLs. Don't nitpick prose unless asked.
