# Universal review checklist

Language-independent questions. Not every item applies to every change. Pick what the change touches.
A finding needs a concrete failure scenario: input/state → wrong behaviour.

## Correctness
- Does the code do what the commit/PR says? Anything said but not done, or done but not said?
- Boundaries: empty collection, zero, one, negative, max int / overflow, NaN, very long strings,
  unicode/multibyte, leap days, DST, time zones, locale-dependent parsing/formatting.
- Off-by-one in loops, slices, ranges, pagination, inclusive vs exclusive bounds.
- Null/None/nil/undefined: can it reach here? Optional chaining hiding a real bug?
- Equality and identity: reference vs value, float equality, case sensitivity, normalisation.
- Integer division, implicit truncation, signed/unsigned mixing, unit mismatches (ms vs s, bytes vs bits).
- Error handling: swallowed exceptions, broad catches, errors logged but not propagated, wrong
  error type, partial state left behind on failure, cleanup on every exit path.
- Changed function signatures/behaviour: are all callers updated? Search for them.
- Feature flags, config defaults and environment-specific branches: is the default safe?
- Copy-paste: duplicated block with one variable not renamed.

## Security
- Untrusted input (HTTP, CLI args, files, env, DB rows written by users, LLM output) reaching a sink:
  shell, SQL/NoSQL, template/HTML, file path, URL fetch, deserializer, regex, eval, log line.
- AuthN/AuthZ: every new endpoint/handler/command checks identity *and* permission on the object
  (IDOR). Checks happen server-side, before side effects.
- Secrets in code, logs, error messages, URLs, client bundles. Secrets compared in constant time.
- Crypto: no homemade crypto, no MD5/SHA1 for security, no ECB, random IVs/nonces, CSPRNG for tokens,
  TLS verification left on, password hashing with bcrypt/scrypt/argon2.
- Path traversal on joins with user input; archive extraction (zip-slip); symlink races; temp files.
- SSRF on user-supplied URLs; open redirects; CORS `*` with credentials; missing CSRF protection.
- Resource exhaustion: unbounded upload/body size, regex backtracking (ReDoS), unbounded loops on input.
- Dependency changes: new packages are real, maintained and pinned; no typosquats; licences compatible.

## Reliability & concurrency
- Shared mutable state accessed from multiple threads/tasks/goroutines/requests without sync.
- Check-then-act races (exists→create, read→modify→write) in code, files or DB rows.
- Locks: ordering (deadlock), held across I/O or await, released on every path.
- Async: un-awaited promises/futures, blocking calls inside async code, fire-and-forget errors lost.
- Resources: files, sockets, DB connections, cursors, GPU memory, subprocesses closed on all paths.
- Network calls: timeouts set, retries bounded with backoff, idempotent when retried.
- Data migrations: reversible, safe on large tables (locks), compatible with old code during deploy.
- Backward compatibility of APIs, wire formats, config files, CLI flags, persisted data.

## Performance (only when plausible at real sizes)
- Complexity: nested loops over large inputs, repeated linear search, quadratic string building.
- N+1 queries, queries in loops, missing index for a new query pattern, SELECT * on wide tables.
- Work in hot paths: allocation, logging, regex compilation, serialization.
- Unbounded caches/queues/collections; reading whole files/responses into memory.

## Tests
- Would a test fail if the change were reverted? If not, the change is untested.
- New branches and error paths covered? Edge cases from the correctness list?
- Tests deterministic: no sleeps for synchronisation, no dependence on order, time, network, randomness without seed.
- Assertions meaningful (not just "no exception"); mocks don't mock the thing under test.

## Maintainability (report only if it will cost something real)
- Names that mislead about behaviour or units.
- Logic duplicated in a way that must be kept in sync.
- Dead code, commented-out code, leftover debug output, TODOs without owner/issue for real gaps.
- Abstraction mismatch: a new layer that adds indirection with no second use; a god function.
- Public API: easy to misuse? Surprising defaults? Documented?
- Comments/docs that are now wrong because of this change.

## Config, infra & build
- Defaults safe for production; secrets not committed; environment-specific values parameterised.
- Containers: pinned base images, non-root user, no secrets in layers, minimal attack surface.
- CI/CD: untrusted PR input in `run:` scripts, overly broad tokens/permissions, unpinned actions.
- IaC: public buckets, 0.0.0.0/0 ingress, missing encryption, destroy-on-change resources.
