# Review rules (example — copy to your repo root as CODEREVIEW.md and edit)

These rules override codereview-ops' generic checklist.

## Must
- All database access goes through `src/repo/`. Raw SQL anywhere else is a **major**.
- Every new HTTP handler checks both authentication and object-level authorization. A missing check is a **blocker**.
- Public API or CLI flag changes need a CHANGELOG entry (**minor**).
- `unwrap()` / `!!` / force-unwrap outside tests is a **major**.

## Ignore
- Formatting and import order: `prettier`, `black` and `gofmt` run in CI.
- Files under `legacy/` unless the change touches their public interface.

## Context
- Payments code (`src/billing/`) handles money in integer minor units (paise/cents), never floats.
- GPU kernels in `kernels/` target sm_80+; warp size is 32; shared memory is limited to 48 KB per block.
