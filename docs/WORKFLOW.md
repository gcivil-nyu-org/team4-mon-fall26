# Team workflow

## Branches

| Branch | Deploys to | Who merges into it |
|---|---|---|
| `testing` | The testing AWS environment (Travis deploys it when the build passes) | Feature branches, through a reviewed PR |
| `main` | Production (Travis deploys it when the build passes) | Only `testing`, after the change has been checked on the testing site |

- Never commit or push to `main` directly, and never open a PR into `main` from a feature branch. Every push to `main` deploys to production.
- Don't commit straight to `testing` either: work on your own branch and merge it through a PR.
- Branch from the latest `testing`: `yourname/short-description` (e.g. `nihal/roster-rules`).
- Open every PR against `testing`, never straight to `main`.

### From your branch to production

1. Branch from `testing`, build, and run the checks below locally.
2. Open a PR into `testing`. It needs a review and a green Travis build, then merge.
3. Travis deploys `testing` to the testing site. Check your change there.
4. Once `testing` is good, a team member opens a PR from `testing` into `main`. It needs a review and a green build, then merge. Travis deploys `main` to production.
5. If `main` ever gets a change that `testing` doesn't have, merge `main` back into `testing` through a PR before the next `testing` → `main` PR.
- Keep PRs to one card where you can. If a PR depends on another open PR, say so at the top of the description.

## Pull requests

- Title: what it does, with card numbers if any ("Cards 3-5: roster rules, remove player, leave team").
- Description: what changed and why, any migrations, how you tested it (commands and manual steps), and screenshots for UI changes.
- Reviewed and approved by someone other than the author before merging.
- Before opening, run what Travis CI runs on every push and PR: `flake8 .`, `coverage run manage.py test` and `coverage report --fail-under=80` (`pip install -r requirements-dev.txt` first). Format with black.

## Issues and ZenHub

- No work without an issue. If one doesn't exist, create it before you start, with acceptance criteria and its parent epic.
- Assign yourself (or the owner) before starting, and keep the ZenHub card current: Backlog → In Progress (branch created) → Review/QA (PR open) → Done (see below).
- Log progress as short comments on the issue: start, PR link, blockers, scope changes.
- Coding agents follow the same rules; the details are in [AGENTS.md](../AGENTS.md#issues-and-zenhub-tracking-required).

## Definition of done

A card is done when:

- It is merged through a pull request reviewed by someone else
- The tests pass (`python manage.py test` locally, and the Travis build is green)
- It works on the deployed site
- The ZenHub card is in Done with the owner's name

## Working agreements

- One owner per card. Pairing is fine, but one name stays on the card.
- Merge to `testing` first, and to `main` only after checking on the testing site.
- Every page extends `templates/base.html` and follows [DESIGN.md](DESIGN.md). Don't add your own layout.
- If you are blocked, say so at standup the same day.

## Data

The database is SQLite for now, so data resets on every deploy. Don't rely on data you entered on a deployed site still being there.
