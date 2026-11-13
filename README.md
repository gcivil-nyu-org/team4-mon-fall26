# team4-mon-fall26 (PlayNYU)

Django project for Team 4.

## Links
- Prod: http://playnyu-prod.eba-ax4phmwp.us-east-2.elasticbeanstalk.com/
- Testing: http://playnyu-test.eba-t3ythqtj.us-east-2.elasticbeanstalk.com/ (deploys from `testing`)

## Docs

Team docs live in [`docs/`](docs/). Link to them instead of copying their content into PRs, chats or prompts.

| Doc | What it covers | Read it when |
|---|---|---|
| [docs/WORKFLOW.md](docs/WORKFLOW.md) | Branches, pull requests, definition of done, working agreements | Before your first PR, and whenever you're unsure where code goes |
| [docs/DESIGN.md](docs/DESIGN.md) | The UI design system: stack, tokens, components, page recipes, UI PR checklist | Before touching any template, CSS or page |
| [docs/E2_CONTRACT.md](docs/E2_CONTRACT.md) | E2 rules: sports, event types, season lifecycle, divisions, data migration | Before working on #106, #107, #108 or #109 |
| [docs/DATA.md](docs/DATA.md) | Facility data: dataset choice, sport codes, dictionary, quality, permits | Before touching facility data, the import or the seed files |
| [docs/DATABASE.md](docs/DATABASE.md) | Database setup: `DATABASE_URL`, Postgres on Neon, migrations on deploy, testing on Postgres | Before setting up an environment, or when using `select_for_update` or raw SQL |
| [docs/PLAN.md](docs/PLAN.md) | Roadmap for E5/E6/E7/E9: what is on `testing`, the Nov 9–15 wave, and what remains | Before picking up results, notifications, chat, or secure/observe work |

Coding agents start from [AGENTS.md](AGENTS.md), which points to these docs. To add a doc: one topic per file in `docs/`, named in caps like the ones above, with a row added to this table in the same PR.

## Branches

- `main`: production (deploys to the production AWS account)
- `testing`: testing (deploys to the testing AWS account)

Work lands on `testing` first. Only tested changes are merged into `main`.

## Local setup

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Open http://127.0.0.1:8000/ to see the home page and http://127.0.0.1:8000/health/ for the health check.

## Run the tests

```bash
python manage.py test
```

## CI and deployment (Travis CI)

Every push and pull request runs `black --check`, `flake8`, the tests and a coverage check (`.travis.yml`).
When the build passes, a push to `testing` deploys to the testing environment and a push to
`main` deploys to production (`playnyu-prod`, us-east-2). Pull request builds never deploy.

Run the same checks locally:

```bash
pip install -r requirements-dev.txt
black --check .
flake8 .
coverage run manage.py test && coverage report
```

Travis needs these variables (Settings > Environment Variables, "Display value in build log" off):

| Variable | Used for |
|---|---|
| `AWS_ACCESS_KEY_ID_PROD`, `AWS_SECRET_ACCESS_KEY_PROD` | Deploy to production |
| `AWS_ACCESS_KEY_ID_TESTING`, `AWS_SECRET_ACCESS_KEY_TESTING` | Deploy to testing |

## Configuration (environment variables)

| Variable | Default | Notes |
|---|---|---|
| `DJANGO_DEBUG` | `True` | Set to `False` on AWS |
| `DJANGO_SECRET_KEY` | dev-only key (only when debug is on) | Required when `DJANGO_DEBUG=False` |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated; add the AWS hostname |
| `DATABASE_URL` | unset (uses SQLite) | Set on AWS to a persistent database; see [docs/DATABASE.md](docs/DATABASE.md) |
| `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | unset (emails print to the console) | Set to send real verification emails over SMTP |
| `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_EMAIL`, `DJANGO_SUPERUSER_PASSWORD` | unset | Admin user created on deploy if it doesn't exist |
| `TEST_PLAYER_EMAIL`, `TEST_PLAYER_PASSWORD` | unset | Regular player account created on each deploy (testing site only) |
| `DEMO_USERS_PASSWORD` | unset | Password for the demo players created on each deploy (`demo.captain1@nyu.edu` to `demo.captain4@nyu.edu`, `demo.player1@nyu.edu` to `demo.player10@nyu.edu`; testing site only). Locally: `DEMO_USERS_PASSWORD=... python manage.py seed_demo_users` |
| `SEED_DEMO_LEAGUE` | unset | Set to any value on the testing site only. Each deploy then runs `seed_demo_league`, which adds demo teams and matches to this semester's seasons. Never set it on production |

Each deploy also runs `seed_league_data` (sports) and then `seed_semester_seasons` (this and next semester's season for every sport). Run them locally in that order: `python manage.py seed_league_data && python manage.py seed_semester_seasons`. Add `--today YYYY-MM-DD` to `seed_semester_seasons` to try another date.

`seed_demo_league` puts four demo teams ("Demo Violets", "Demo Bobcats", "Demo Torches", "Demo Arches") in each of this semester's seasons, with demo players as captains and roster members. It then schedules a round-robin: half the matches are played with scores, half are upcoming. It only adds what is missing and never changes existing teams or matches. It needs the demo players, the seasons and the facilities, so run it last. Locally, use `--force` in place of the variable: `python manage.py seed_demo_league --force`. It also takes `--today YYYY-MM-DD`.

## Project layout

```
manage.py
playnyu/    project settings and root URLs
core/       starter app (home page and health check)
```

Database: SQLite locally (`db.sqlite3`, not committed), Postgres on Neon for the deployed sites ([docs/DATABASE.md](docs/DATABASE.md)).

[![Build Status](https://app.travis-ci.com/gcivil-nyu-org/team4-mon-fall26.svg?branch=main)](https://app.travis-ci.com/gcivil-nyu-org/team4-mon-fall26)
[![Coverage Status](https://coveralls.io/repos/github/gcivil-nyu-org/team4-mon-fall26/badge.svg?branch=main)](https://coveralls.io/github/gcivil-nyu-org/team4-mon-fall26?branch=main)
