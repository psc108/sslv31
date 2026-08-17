# Contributing to LabTool

Ground rules for working on this repo with more than one person. Keep it simple:
`main` must always be a working product. Everything else follows from that.

## Branches

- **Never commit directly to `main`.** Create a branch per feature or fix:
  `feature/short-name` or `fix/short-name`.
- Keep branches short-lived — days, not weeks. The longer a branch lives
  without merging, the more painful the eventual merge is. If a feature is
  genuinely big, land it in smaller PRs behind a flag (see below) rather than
  one huge branch.
- Pull `main` into your branch regularly (or rebase) so you're not
  discovering conflicts for the first time when you open the PR.

## Commits

- Prefer several small, logical commits over one giant one (e.g. "model +
  migration", then "API endpoints", then "frontend") — it makes a bad change
  revertable or bisectable without taking the whole feature out with it.
- Write commit messages that explain *why*, not just what changed.

## Migrations — the sharp edge

Alembic migrations in `backend/alembic/versions/` are numbered sequentially
by hand (`089_...`, `090_...`). This is the one place two people working in
parallel will silently collide — both picking `091` on separate branches.

- Before creating a new migration, pull latest `main` and check the highest
  existing number.
- If someone else merges a same-numbered migration before your PR lands,
  renumber yours (and its `down_revision`) on your branch before merging.
  Don't let two migrations share a number, and don't edit a migration that's
  already on `main` — write a new one instead.

## Pull requests

- Every branch goes through a PR into `main`, even solo-authored work — this
  is the checkpoint where migration-number collisions and merge conflicts
  get caught before they hit `main`, not after.
- Before opening a PR, run the pre-commit checks (`ruff`, `mypy`, the
  schema-drift check) and the `backend/tests/` pytest suite.
- Get one of the other two people to look over anything touching migrations,
  auth/RBAC, or shared models. Small, contained fixes can be self-merged.

## What "done" means before merging

This mirrors the discipline already used throughout this project — don't
skip steps because the code compiles:

1. Backend changes parse cleanly and `alembic upgrade head` applies without
   error.
2. Frontend changes pass `npx tsc -b` with no new errors.
3. `docker compose -f docker/docker-compose.yml build certmanager` actually
   builds.
4. The change is live-verified against the running container — curl the
   endpoint, click through the UI — not just "the code compiles."
5. Any user-facing behaviour change is reflected in the relevant
   `Documentation/*.md` guide and in-app Help section.
6. Test data / scratch files created while verifying are cleaned up before
   merging.

## Optional / in-progress features

Don't let half-finished work block `main`, and don't maintain a long-lived
branch just to keep a feature "off" for some instances. Gate it behind a
flag instead:

- **Deploy-time toggle** → an environment variable (see `SCEP_ENABLED` in
  `docker/docker-compose.yml`).
- **Runtime, per-instance toggle** → a settings-table row an admin can flip
  (see `BMSettings`).

Either way, the code lands on `main` behind the flag, off by default until
it's ready, rather than diverging in a branch.

## Doing this in your IDE

Both IDEs need to be pointed at `github.dxc.com` (this is GitHub Enterprise,
not github.com) before PR creation/review will work from inside the editor.

### VS Code

1. Install the **GitHub Pull Requests and Issues** extension.
2. First use will prompt you to sign in — choose "Sign in to GitHub
   Enterprise Server" and enter `github.dxc.com`, not the github.com option.
3. Branching: bottom-left status bar shows the current branch — click it,
   then "Create new branch from..." off `main`. Use `feature/short-name` or
   `fix/short-name`.
4. Commit: Source Control panel (`Ctrl+Shift+G`) — stage, write a message,
   commit. Push via the "..." menu or the sync arrows in the status bar.
5. Open the PR: Source Control panel → "GitHub Pull Requests" section →
   "Create Pull Request", base = `main`. Review/comments happen in the same
   panel without leaving the editor.

### IntelliJ IDEA Ultimate

1. **Settings → Version Control → GitHub** → add an account, choose
   "GitHub Enterprise", server URL `github.dxc.com`, authenticate with a
   personal access token.
2. Branching: bottom-right branch widget → `main` → "New Branch from
   Selected...". Use the same `feature/short-name` / `fix/short-name`
   naming.
3. Commit: `Ctrl+K` (Commit tool window) — review the diff per file, write a
   message, commit. Ultimate runs your configured inspections/checks on
   commit if "Analyze code" is ticked in the commit dialog — worth leaving
   on, it'll catch some of what pre-commit would.
4. Push: `Ctrl+Shift+K`, or tick "Push" in the commit dialog to do both at
   once.
5. Open the PR: **Git tool window → Pull Requests tab** → "New Pull
   Request", base = `main`. Reviews, comments, and merging can all be done
   from this tab.

Either way, still run the pre-commit checks and `backend/tests/` locally
before pushing — the IDE's built-in inspections don't replace `ruff`,
`mypy`, or the schema-drift check.

## Repo-specific gotchas

- Anything under `playbooks/` is baked into the Docker image at build time,
  not live-mounted — changes there need an image rebuild before they take
  effect, even in local testing.
- On Windows, avoid `git stash` in this repo — CRLF conversion has corrupted
  `entrypoint.sh`'s line endings on stash/pop before. Commit or discard
  instead.
