---
name: pr-review
description: "This skill should be used when the user asks to \"review PR #123\", \"review this pull request\", \"review this merge request\", pastes a GitHub/GitLab PR URL to review, asks to \"post review comments\" on a PR, or runs /pr-review or /codereview-ops:pr-review. Language-agnostic."
argument-hint: "<PR number or URL> [--post] [--security]"
metadata:
  version: "0.1.0"
---

# codereview-ops: pull request review

Arguments: $ARGUMENTS

## 1. Fetch the PR without disturbing the user's checkout

GitHub (requires `gh` authenticated; check with `gh auth status`):

```bash
gh pr view <N|URL> --json number,title,body,author,baseRefName,headRefName,headRefOid,url,files,commits
gh pr diff <N|URL> > /tmp/codereview-ops-pr-<N>.patch
```

For full-file context, prefer a separate worktree over switching branches:

```bash
git fetch origin pull/<N>/head:codereview-ops/pr-<N>
git worktree add --detach /tmp/codereview-ops-pr-<N> codereview-ops/pr-<N>
```

then run the collector **inside the worktree** against the PR's base:
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/collect.py" --root /tmp/codereview-ops-pr-<N> --base origin/<baseRefName>`.
If not inside a clone of the repo, use the patch alone:
`collect.py --diff-file /tmp/codereview-ops-pr-<N>.patch` (and fetch individual files with
`gh api repos/{owner}/{repo}/contents/{path}?ref=<headRefOid>` when context is needed).

GitLab: `glab mr view <N>` / `glab mr diff <N>` work the same way. Other hosts: ask the user for the
patch or branch.

## 2. Review

Follow the `review` skill from step 2 onward. The PR title, body and linked issue are the intent;
existing review comments (`gh pr view <N> --comments`) tell you what's already been raised, so don't
repeat it. Check PR hygiene only where it matters: unrelated changes mixed in, missing tests for
risky logic, missing migration/rollback notes.

## 3. Report, and post only on request

Always show the report in chat first. Post to the PR **only if the user passed `--post` or
explicitly asks**, after showing them what will be posted:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/report.py" <workdir>/findings.json --pr-review <workdir>/pr-review.json --quiet
gh api repos/{owner}/{repo}/pulls/<N>/reviews --method POST --input <workdir>/pr-review.json
```

The payload uses `event: "COMMENT"`. Never approve or request changes on the user's behalf unless
they say so (then set `event` to `APPROVE` / `REQUEST_CHANGES`). Inline comments are attached only to lines
inside the diff; other findings go in the review body. Finally remove the worktree:
`git worktree remove /tmp/codereview-ops-pr-<N> && git branch -D codereview-ops/pr-<N>`.
