# PR and release workflow (for AI agents)

This is how a change goes from a local branch to production in `fer336/agente-ai`.
Follow it end to end without asking the user for each step. The user only decides
**push/PR** (when not already asked for) and **merge**.

## TL;DR

1. Branch from `origin/main` → conventional commits → local checks.
2. Push the branch → create an issue (already labeled `status:approved`) → open the PR with
   `Closes #N`, a conventional title (`fix(...)` / `feat(...)`), and one `type:*` label.
3. CI (`test`) passes → the user merges with **squash**.
4. **Do not create tags or releases by hand.** Merging to `main` creates the tag, the
   GitHub Release, the image build, the `docker-stack.yml` pin, and the deploy automatically.
5. Check that the automation ran (see "Verify the release").

## How the pipeline works (source: `.github/workflows/`)

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| `ci.yml` | PR to `main`, push to `main` | `uv sync --frozen --extra dev`, `ruff check .`, `mypy app/`, `pytest` |
| `auto-tag.yml` | push to `main` | Scans commit **subjects** since the last `vX.Y.Z` tag. If a bump is needed, runs `gh release create vX.Y.Z --target main --generate-notes` with `RELEASE_PUSH_TOKEN` |
| `release.yml` | `release: published` | Validates the SemVer tag. Runs lint, types and tests. Builds `ghcr.io/fer336/agente-ai:vX.Y.Z` and pushes it. Commits `chore(release): pin backend image to vX.Y.Z` to `main`. Triggers the Portainer webhook. Polls `https://agent.qeva-ai.com/ready` |

The bump comes from the commit subject, and with a squash merge **the subject is the PR title**:

| Subject starts with | Bump |
|---------------------|------|
| contains `BREAKING CHANGE` or `!:` (e.g. `feat!:`) | major |
| `feat:` / `feat(scope):` / `Feat/...` | minor |
| `fix:` / `fix(scope):` / `perf:` / `Fix/...` | patch |
| `chore`, `docs`, `style`, `refactor`, `test`, `ci`, `build`, anything else | **no release** |

`auto-tag.yml` skips itself when the head commit starts with `chore(release): pin`. This
prevents a loop with the pin commit.

## Step by step

### 1. Branch

- Always start from an up-to-date `origin/main`: `git fetch origin`.
- Branch name: `^(feat|fix|chore|docs|style|refactor|perf|test|build|ci|revert)/[a-z0-9._-]+$`,
  for example `fix/first-visit-question-buttons`.
- If the main checkout has uncommitted user work, **never stash, reset or switch it**. Use a
  worktree next to the repo instead:
  `git worktree add -b fix/<name> ../agente-ai-worktrees/<name> origin/main`.

### 2. Commits

- Conventional Commits: `type(scope): description`, e.g. `fix(appointments): ...`.
- **No `Co-Authored-By` trailers and no AI attribution** in commits or PR bodies. This is a
  user rule.
- Keep tests with the behavior they cover in the same commit.

### 3. Local checks (same as CI)

```bash
uv run pytest
uv run ruff check .
uv run mypy app/
uv run ruff format --check <changed files>   # repo-wide format check has pre-existing drift
```

Known environmental failures that may appear locally but pass in CI: the 3 tests in
`tests/integration/test_redis_debounce_lock.py` (they need Redis). Any other failure blocks
the PR.

### 4. Push, issue, PR

No workflow enforces the issue or its approval. The issue is only for traceability.
**Do not ask the user to approve it.** The user's request to ship is the approval, so create
the issue already labeled `status:approved`.

```bash
git push -u origin fix/<name>

gh issue create \
  --title "fix(appointments): <problem in one line>" \
  --label "type:bug" --label "status:approved" \
  --body "## Problem ... ## Expected ..."

gh pr create --base main --head fix/<name> \
  --title "fix(appointments): <what the PR does>" \
  --label "type:bug" \
  --body "Closes #<issue>

## Type
- [x] Bug fix

## Summary
- ...

## Changes
| File | Change |
|------|--------|

## Test Plan
- [x] uv run pytest ...
"
```

- **The PR title decides the release.** Use `fix(...)` for patches and `feat(...)` for
  minor releases. A `chore`/`docs`/`style`/`refactor`/`test` title **will not deploy**.
- Labels that exist: `type:bug`, `type:chore`, `type:refactor`, `status:approved`,
  `enhancement`, `documentation`. Map `fix` → `type:bug`, `chore`/`style` → `type:chore`,
  `feat` → `enhancement` (there is no `type:feature`), `docs` → `documentation`.

### 5. CI and merge

- Wait for CI: `gh pr checks <pr>` must show `test pass`.
- Merging is the user's decision. If the user explicitly says to merge, use
  **squash** only:
  `gh pr merge <pr> --squash`.
  The squash subject must stay the conventional PR title. GitHub appends ` (#N)`,
  which is fine.
- Never push directly to `main`, and never edit the image tag in `docker-stack.yml` by hand.
  The pipeline owns both.

### 6. Verify the release

```bash
gh run list -L 6 --json workflowName,event,headBranch,conclusion,displayTitle \
  --jq '.[] | "\(.workflowName) | \(.event) | \(.conclusion) | \(.displayTitle)"'
gh release list -L 3
git fetch origin && git log --oneline origin/main -3   # expect "chore(release): pin backend image to vX.Y.Z"
```

A successful run shows this sequence: `CI` (push, main) success → `Auto Tag Release` success
→ a new `vX.Y.Z` in `gh release list` → `Release` success (all jobs, including
`verify-health`) → the pin commit on `main`. Report the version to the user.

## Deploy gotchas

- **One release at a time.** Merge one PR, wait until its `Release` run finishes (including
  `verify-health`) and the pin commit lands on `main`, then merge the next. Versions and the
  pinned `docker-stack.yml` overlap otherwise.
- **A green release does not prove the new version runs.** `verify-health` polls `/ready`,
  which the previous version also answers. Confirm the deployed image on the server:
  `docker service inspect agente-clinica_backend --format '{{.Spec.TaskTemplate.ContainerSpec.Image}}'`
  must show the new `vX.Y.Z`.
- **Stack file changes that reference a Swarm secret.** If a PR changes which secret
  `docker-stack.yml` uses, the user must create that secret **before** the merge. Otherwise
  Portainer cannot deploy: the release stays green while production keeps the old version.
  Secrets are immutable, so a changed value means a new secret name.
- **A release redeploys the stack file.** Environment variables added by hand with
  `docker service update --env-add` are lost on the next release. Persistent settings belong
  in the `agente_ai_backend_env` secret.
- **Stacked branches and squash merges.** After the base PR is squash-merged, move the
  stacked branch with `git rebase --onto origin/main <last commit of the old base> <branch>`,
  and expect conflicts in files both branches touched.
- **Don't merge during an audit.** The eval flags live in the production secret, but a
  release restarts the backend and drops the eval sessions in memory.

## Why a tag or release sometimes did not appear

| Cause | Fix |
|-------|-----|
| The PR title was `chore(...)`, `docs(...)`, `style(...)`, `refactor(...)`, `test(...)` or free text | Intended behavior: no release. If the change must deploy, the title must be `fix(...)` or `feat(...)` **before** merging |
| The agent created the tag with `git tag` + `git push --tags` | `release.yml` only listens to `release: published`, so a bare tag does nothing. Don't do it |
| A release was created with the default `GITHUB_TOKEN` | GitHub does not fire workflows for events created with that token. Only `RELEASE_PUSH_TOKEN` (in `auto-tag.yml`) or a user's own credentials trigger `release.yml` |
| The agent created a release by hand *and* auto-tag also ran | You get duplicated or skipped versions. Let `auto-tag.yml` do it |
| `Release` failed (tests, build, health) | Read the log with `gh run view <id> --log-failed`, fix it with a new `fix(...)` PR, or `gh run rerun <id>` for a transient failure |

### Manual recovery (only with explicit user authorization)

If a `fix`/`feat` change reached `main` and `Auto Tag Release` did not create a release:

1. Find the last tag with `gh release list -L 1` and compute the next SemVer.
2. `gh release create vX.Y.Z --target main --title vX.Y.Z --generate-notes`, using the
   user's own `gh` auth. That publishes a release, which triggers `release.yml`.
3. Verify it as in step 6.

## Checklist for "subilo" / "hacé el PR"

- [ ] Branch from `origin/main` (worktree if the main checkout is dirty)
- [ ] Conventional commits, no AI attribution
- [ ] `pytest`, `ruff check`, `mypy` green (except the known environmental failures)
- [ ] `git push -u origin <branch>`
- [ ] Issue created with a type label plus `status:approved`, without asking for approval
- [ ] PR with `Closes #N`, a conventional `fix(...)`/`feat(...)` title and one matching label
- [ ] `gh pr checks` → `test pass`
- [ ] The user merges with squash, or you do if told to (`gh pr merge --squash`)
- [ ] Verify `Auto Tag Release` → new release → `Release` success → pin commit
- [ ] Confirm the deployed image tag on the server, then report the version
- [ ] Never create tags or releases by hand unless the user asks for recovery
