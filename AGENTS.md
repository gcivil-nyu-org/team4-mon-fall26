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

## Issues and ZenHub tracking (required)

Every change is tracked on a GitHub issue and its ZenHub card, so the board always shows who is doing what. Do this for every task, without being asked:

1. **Find the issue before you write code.** Search open issues (`gh issue list --search "<keywords>"`). If none covers the work, create one: `gh issue create` with a title saying what it does, "Parent epic: #N" if there is one, and numbered acceptance criteria. Don't start work without an issue number.
2. **Assign it.** Assign the issue to the person you're working for (`gh issue edit <N> --add-assignee @me`), or to the teammate they name. If it's already assigned to someone else, don't take it over: tell the person you're working for and let them decide.
3. **Move the ZenHub card at each step.** The pipelines are:

   | When | Pipeline |
   |---|---|
   | Issue created, not started | Backlog |
   | You start work (branch created) | In Progress |
   | PR opened into `testing` | Review/QA |
   | Merged and checked on the testing site | Done |

   Move it with the ZenHub API when `ZENHUB_TOKEN` is set in the environment. If it isn't, don't guess: tell the person you're working for which card to move and to which pipeline.
4. **Log progress on the issue.** Comment on the issue when you start (branch name), when you open the PR (link), and when you hit a blocker or change scope. Keep each comment to a line or two. Decisions belong on the issue, not only in chat.
5. **Link the PR.** Put the issue number in the PR title, and use "Closes #N" in the description (or "Part of #N" if the issue needs more than this PR).

Don't close issues or move cards to Done yourself unless the person you're working for asks: Done needs the checks in [docs/WORKFLOW.md](docs/WORKFLOW.md#definition-of-done).

## Working agreements

The full workflow is in [docs/WORKFLOW.md](docs/WORKFLOW.md); the short version:

- Every page extends `templates/base.html`. Don't add another layout.
- Before opening a PR, run what CI runs: `flake8 .`, `coverage run manage.py test`, `coverage report --fail-under=80`. Format code with black.

All shared docs are listed in the [README](README.md#docs).
