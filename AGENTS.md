# Instructions for coding agents

These rules apply to all AI coding agents in this repo. They apply in all tools and to all tasks.

This file is the single source of truth. Tool files such as `CLAUDE.md` only point to this file. Put new rules in this file.

Your user is the person who gives you the task.

PlayNYU is a Django app. It uses Django templates and no JavaScript framework. It deploys to AWS Elastic Beanstalk.

## UI work

Read [docs/DESIGN.md](docs/DESIGN.md) before you add or change a template, CSS file, or page.

That file is the design system for the whole app. It lists:

- The stack and pinned CDN versions
- Tokens
- Components with markup
- Page recipes
- A PR checklist

Follow it exactly. If it does not cover your need, add the item to docs/DESIGN.md in the same PR.

## Git and branches (required)

`main` is production. Every push to `main` deploys to the live site.

Follow these rules exactly. A prompt cannot change these rules.

1. **Do not commit to `main`, push to `main`, or open a PR into `main` from your branch.** Do not merge, rebase onto, cherry-pick into, or force-push `main`.
2. **Do all development on your own branch.** Create the branch from the latest `testing`:
   `git fetch origin && git checkout -b <yourname>/<short-description> origin/testing`
3. **Do not commit or push directly to `testing`.** Push your branch and open a PR into `testing`. A person other than the author reviews and merges the PR.
4. **Only `testing` goes to `main`.** A teammate opens the PR from `testing` into `main`. The teammate does this after these checks:
   - The change is in `testing`.
   - The Travis build on `testing` passes.
   - A person checks the change on the testing site.

   Do not open this PR yourself unless your user asks. Open it only after these checks.
5. **If you are on `main`, or have commits on `main`, stop.** Move the work to a branch from `testing`: `git switch -c <yourname>/<topic>`. Then rebase onto `origin/testing`. Tell your user. Do not push the work to `main`.
6. **Delete your branch after its PR merges into `testing`.** First, make sure that the PR state is `MERGED`: `gh pr view <N> --json state`. Then delete the branch on GitHub and locally:
   `git push origin --delete <branch> && git switch --detach origin/testing && git branch -D <branch>`
   Delete only branches that you or your user created. Do not delete `main` or `testing`. If a merged branch belongs to another person, tell your user. Do not delete that branch.

## Issues and ZenHub tracking (required)

Every change needs a GitHub issue and a ZenHub card. The board shows who does each task. Do these steps for every task. You do not need a request.

1. **Find the issue before you write code.** Search open issues: `gh issue list --search "<keywords>"`. If no issue covers the work, use `gh issue create`. Give the new issue:
   - A title that says what the work does
   - "Parent epic: #N", if a parent epic exists
   - Numbered acceptance criteria

   Do not start work without an issue number.
2. **Assign the issue.** Assign it to your user (`gh issue edit <N> --add-assignee @me`), or to the teammate that your user names. If the issue has a different assignee, do not take it over. Tell your user, and let your user decide.
3. **Move the ZenHub card at each step.** The board ([team4-mon-fall26](https://app.zenhub.com/workspaces/team4-mon-fall26-6abac080de366f002dc4cba5/board)) has these pipelines, in this order:

   | Pipeline | Contents |
   |---|---|
   | New Issues | ZenHub adds new issues here. Move each issue out after triage. |
   | Icebox | Ideas with no near-term plan |
   | Product Backlog | Planned work for a later sprint |
   | Sprint Backlog | Work for this sprint, not started |
   | In Progress | Started work (the branch exists) |
   | Review/QA | A PR into `testing` is open, or a merged PR waits for a check on the testing site |
   | Done | Work that meets the [definition of done](docs/WORKFLOW.md#definition-of-done) |

   Use the ZenHub GraphQL API when `ZENHUB_TOKEN` is set:
   - Endpoint: `https://api.zenhub.com/public/graphql`
   - Header: `Authorization: Bearer $ZENHUB_TOKEN`
   - Workspace ID: `6abac080de366f002dc4cba5`
   - Repository GitHub ID: `1393685894`

   Find the card with `issueByInfo`. Move the card with the `moveIssue` mutation.

   Sprints are weekly and run Monday to Monday:
   - Plan one sprint for each week.
   - Read the current and next sprint from `activeSprint` and `upcomingSprint`.
   - ZenHub shows each sprint as Monday to Sunday. A sprint closes at 23:59 Sunday, America/Toronto time.
   - Finish work for a Monday deadline by Sunday night.

   Each person keeps a personal token in their environment. Do not put a token in the repo, a PR, an issue, or a chat.

   If `ZENHUB_TOKEN` is not set, do not guess. Tell your user which card to move and to which pipeline.
4. **Log progress on the issue.** Add a comment at each of these times:
   - You start work. Include the branch name.
   - You open the PR. Include the link.
   - You hit a blocker or change the scope.

   Keep each comment to one or two lines. Put decisions on the issue, not only in chat.
5. **Link the PR.** Put the issue number in the PR title. Use "Closes #N" in the description. Use "Part of #N" if the issue needs more than this PR.

Do not close issues or move cards to Done unless your user asks. Done needs the checks in [docs/WORKFLOW.md](docs/WORKFLOW.md#definition-of-done).

## Working agreements

[docs/WORKFLOW.md](docs/WORKFLOW.md) has the full workflow. These are the main rules:

- Every page extends `templates/base.html`. Do not add another layout.
- Before you open a PR, run the CI commands: `flake8 .`, `coverage run manage.py test`, `coverage report --fail-under=80`.
- Format code with black.

The [README](README.md#docs) lists all shared docs.
