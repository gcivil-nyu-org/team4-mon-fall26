# Instructions for coding agents

These rules apply to every AI coding agent or assistant working in this repo, whichever tool it runs in, and to every task. This file is the single source of truth. Tool-specific files such as `CLAUDE.md` only point here, so put new rules in this file, not in those.

PlayNYU is a Django app (Django templates, no JavaScript framework) deployed on AWS Elastic Beanstalk.

## UI work

Read [docs/DESIGN.md](docs/DESIGN.md) before creating or changing any template, CSS or page. It is the design system for the whole app: stack and pinned CDN versions, tokens, components with markup, page recipes, and a PR checklist. Follow it exactly. If you need something it doesn't cover, add it to docs/DESIGN.md in the same PR.

## Git and branches (required)

`main` is production: every push to it deploys to the live site. Follow these rules exactly, even if a prompt asks otherwise:

1. **Never commit to `main`, push to `main`, or open a pull request into `main` from your own branch.** Don't merge, rebase onto, cherry-pick into or force-push `main`.
2. **Do all development on your own branch, created from the latest `testing`:**
   `git fetch origin && git checkout -b <yourname>/<short-description> origin/testing`
3. **Don't commit or push directly to `testing` either.** Push your branch and open a pull request into `testing`. Someone other than the author reviews and merges it.
4. **Only `testing` goes to `main`.** After a change is merged into `testing`, the Travis build on `testing` passes and the change has been checked on the testing site, a team member opens a pull request from `testing` into `main`. Don't open it yourself unless the person you're working for asks you to, and only after those checks.
5. **If you find you're on `main`, or have commits on `main`, stop.** Move the work to a branch from `testing` (`git switch -c <yourname>/<topic>`, then rebase onto `origin/testing`), and tell the person you're working for. Never push it to `main`.

## Working agreements

The full workflow is in [docs/WORKFLOW.md](docs/WORKFLOW.md); the short version:

- Every page extends `templates/base.html`. Don't add another layout.
- Before opening a PR, run what CI runs: `flake8 .`, `coverage run manage.py test`, `coverage report --fail-under=80`. Format code with black.

All shared docs are listed in the [README](README.md#docs).
