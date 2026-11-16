# CI speed (#267) design

## Intent

Cut the Travis build from about 38 minutes per job to about 10 minutes or less. Keep the checks the build does today, keep coverage at `--fail-under=80`, and keep deploys the same.

## Measured today (origin/testing, build 241)

| Job | Step | Time |
|---|---|---|
| 641622481 SQLite + coverage | install, `black --check`, `flake8` | about 20 s |
| | `coverage run manage.py test` | 1572 tests, 2196 s, `OK (skipped=2)` |
| | whole job | about 38 min |
| 641622482 Postgres | `python manage.py test` | 1572 tests, 1944 s, `OK (skipped=1)` |
| | whole job | about 33 min |

- Each feature branch with an open PR builds twice (push and pull_request), for example builds 240 and 241.
- `playnyu/settings.py` has no `PASSWORD_HASHERS`, so tests use Django 6.1's PBKDF2 with 1,500,000 iterations. One hash takes 92 ms on a local Apple-silicon Mac, and likely 0.3 to 0.5 s on a Travis vCPU.
- Test helpers hash a password for almost every user: 391 `make_user(` and 45 `create_user(` calls, all with `password="pass12345!"` or similar. The suite has 121 `setUp` methods and 25 `setUpTestData` methods, so most tests create their users again for each test. `seed_demo_users` (7 calls in tests) hashes one password for each demo user.
- The Postgres job without coverage (1944 s) is almost as slow as the SQLite job with coverage (2196 s). Coverage slows Python code but not hashlib's C code, so most of the time is in C-level work. Password hashing is the likely cause.
- The test log has about 1700 lines of `django.request` 403 tracebacks. They cost little time.

## Goals

1. Tests use a fast password hasher. Production, `runserver` and management commands keep Django's default hashers.
2. Both jobs run tests in parallel. Coverage combines the worker data and still enforces `--fail-under=80` with the same `source` and `omit`.
3. Push builds run only for `testing` and `main`. Each PR gets one PR build.
4. The Postgres job still runs `RoleLockTests` and `RoleRaceTests` (`select_for_update`, threads).
5. Deploys to `playnyu-test` and `playnyu-prod` work as before.
6. Before and after times are recorded on #267.

## Non-goals

- Rewrite tests from `setUp` to `setUpTestData`. This is a follow-up if the build is still slow.
- Silence the 403 log noise.
- Make the deploy wait for the Postgres job (today the SQLite job deploys even if the Postgres job fails). Note it; do not fix it here.
- Fix `omit`, which skips `*/tests.py` but not `test_*.py` files. Coverage stays the same as today.

## Approaches

### 1. Fast hasher in tests only

| Option | How | For | Against |
|---|---|---|---|
| **A. `TESTING` flag (recommended)** | In `settings.py`: `TESTING = sys.argv[1:2] == ["test"]`, then `PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]` when true. | Works for `manage.py test`, `coverage run manage.py test`, `python -m django test` and spawned workers (multiprocessing spawn copies `sys.argv` to children). No command changes. | Reads `sys.argv`, so it is a small hidden rule. A subprocess test pins it. |
| B. `playnyu/settings_test.py` | `from .settings import *` plus the hasher. Travis sets `DJANGO_SETTINGS_MODULE` or passes `--settings`. | Explicit. Production cannot load it by mistake. | Every local `manage.py test` must add `--settings`, or it is slow again. One more file. |
| C. Custom `TEST_RUNNER` | Override `setup_test_environment` to set the hasher. | Only the test command uses it. | Spawned workers call the module-level `setup_test_environment`, not the runner's method, so macOS parallel runs keep the slow hasher. Most code. |

Production checks: Elastic Beanstalk runs gunicorn (`sys.argv[1]` is not `test`). `runserver`, `migrate`, `seed_*` and `shell` have other first arguments. No test checks the hash format: the 7 `check_password` and 4 `has_usable_password`/`set_unusable_password` checks work with any hasher. `AUTH_PASSWORD_VALIDATORS` (strength rules) do not change.

### 2. Parallel tests

- Use `manage.py test --parallel auto`. Django starts one worker for each CPU (`multiprocessing.cpu_count()`, or `DJANGO_TEST_PROCESSES`). Travis has about 2 vCPUs; a Mac has more.
- Coverage: set these in `[coverage:run]` in `setup.cfg`. Coverage reads only the config file in child processes, so they cannot be command-line flags.
  - `parallel = true`
  - `concurrency = multiprocessing,thread` (keep `thread`, so code in the race-test threads still counts)
  - `source` and `omit` stay in the same section, so workers use them.
- Then `coverage combine` before `coverage report --fail-under=80`. Without `combine`, `report` finds no data.
- Workers exit normally (`pool.close()` then `pool.join()`), so coverage saves their data.
- Add `tblib` to `requirements-dev.txt`. Django uses it to send readable tracebacks from workers.
- SQLite (Linux, Python 3.12, fork): each worker gets a copy of the in-memory test database.
- SQLite (macOS, spawn; the local venv is Python 3.14.7): Django writes `default_<n>.sqlite3` in the repo folder, then loads it into a shared in-memory database. It deletes the files at the end. A crash can leave them, so add `default_*.sqlite3` and `.coverage.*` to `.gitignore`.
- Postgres: Django clones `test_playnyu` to `test_playnyu_<n>` with `CREATE DATABASE ... TEMPLATE`. The CI user `postgres` is a superuser, so this works.

Parallel safety review:

| Test | Risk | Verdict |
|---|---|---|
| `accounts/test_role_admin.py` `RoleRaceTests` (`TransactionTestCase`, 2 threads, `skipUnlessDBFeature("has_select_for_update")`) | Threads open new connections | Safe. Django updates the worker's `settings_dict` in place, so new threads connect to the worker's clone. Runs only on Postgres. |
| `RoleLockTests` | Reads captured SQL | Safe, per process. |
| `audit/tests.py`, `notifications/tests.py` threads | Check a thread-local mute flag, no DB | Safe. |
| `chat/test_migrations.py`, `teams/test_season_lifecycle.py` `SeasonStateMigrationTests`, `teams/tests.py` `SportBackfillMigrationTests` (`TransactionTestCase` + `MigrationExecutor`) | Migrate the schema back and forward | Safe. Each worker has its own database. Same order rules as serial (Django runs `TransactionTestCase` last). |
| `facilities/test_seed_facilities.py`, `matches/test_seed_class_league.py`, `matches/test_seed_match_details.py` | Temp files | Safe. `tempfile` gives unique names. |
| `teams/test_seed_league_data.py` | `mock.patch.dict(os.environ)` | Safe, per process. |
| `teams/test_roster_rules.py` `ConcurrencySettingsTests` | Reads `transaction_mode` `IMMEDIATE` | Safe. Clone settings keep `OPTIONS`. |

No test uses a fixed port, `LiveServerTestCase`, `MEDIA_ROOT` or a shared file. Parallel runs can still show hidden order dependencies. Fix a test if one appears; do not drop `--parallel`.

### 3. No duplicate builds

| Option | For | Against |
|---|---|---|
| **A. Build-level `if: type = pull_request OR branch IN (testing, main)` (recommended)** | Says the rule in one line. PR builds run for any base branch (also stacked PRs). | Travis "conditions" syntax; a typo skips all builds. Check the first PR build. |
| B. `branches: only: [testing, main]` | Common Travis pattern. | For PR builds Travis checks the PR's base branch against the list. PRs into `testing` and `main` still build, but a stacked PR into a feature branch does not. |

Deploys do not change. They already need a push build (`on: branch: testing` or `main`, `condition: $CI_DB != postgres`), and the `if:` keeps push builds for those two branches.

Also turn on "Auto cancel branch builds" and "Auto cancel pull request builds" in Travis settings (repo admin, no code). A new push then cancels the old build.

### 4. Extras

| Extra | Cost | Benefit | Recommendation |
|---|---|---|---|
| pip cache | Present (`cache: pip`) | Install is about 20 s | Keep. |
| `--keepdb` | None | None: each Travis VM is new | Skip. |
| Faster SQLite test db | None | Django already uses in-memory SQLite | Skip. |
| `--buffer` | Hides output of passing tests | Logging's `StreamHandler` keeps the real `stderr`, so the 403 tracebacks stay. Little gain. | Skip. |
| Slow-test work | Edits many test files | Unknown until measured | Measure with `--durations 20` (Django 5.0+, Python 3.12+). Likely slowest: the three migration test classes, `RoleRaceTests`, `SeedDemoLeagueTests` setup, `teams/tests.py` and `teams/test_roster_rules.py` (most users per test). Record the list on #267; change nothing now. |
| Postgres job only on push to `testing`/`main` | A `select_for_update` bug reaches `testing` and, since the SQLite job deploys alone, the testing site | Saves the second job on PRs | Skip. After the hasher and parallel changes the Postgres job is short, and production runs Postgres. |

## Decisions

Approved on 2026-11-16.

1. Hasher detection: a **`TESTING` flag in `settings.py`**, based on `sys.argv`, sets `PASSWORD_HASHERS` to `MD5PasswordHasher` for test runs only. A subprocess test checks that `runserver`, `migrate`, gunicorn and `shell test` keep the default hasher.
2. Fast hasher: **`MD5PasswordHasher`**.
3. Worker count: **`--parallel auto`**.
4. Coverage: `parallel = true` and `concurrency = multiprocessing,thread` in `setup.cfg`. Run `coverage combine` before `coverage report --fail-under=80`. Add `tblib` to `requirements-dev.txt`.
5. Duplicate builds: a **build-level `if: type = pull_request OR branch IN (testing, main)`**. The deploy blocks do not change.
6. Postgres job on PRs: **keep**, and run it in parallel too.
7. Extras: keep the pip cache. No `--keepdb` and no `--buffer`. Measure `--durations 20` and report it; do not change tests.
8. Travis auto-cancel: a UI setting. Do not change it here; the PR lists it as a step for a repo admin.
9. Proof: local timings at each stage, then build 241 against the PR build, on #267.
10. One commit per change, so each one can be reverted alone.

## Risks

- A `sys.argv` change in a future Django could miss the flag. The subprocess test and a local timing check catch it.
- MD5 hashes in the test DB are weak. They exist only in test databases.
- Parallel runs can expose test order bugs or unpicklable failures. `tblib` shows the traceback.
- Stale `.coverage.*` files from a local crash get combined into the next report. Run `coverage erase` first locally.
- A wrong `if:` stops all builds. The PR build itself is the check, and the push of `nihal/ci-speed` must show no push build.
- On Travis's 2 vCPUs parallel gives at most about 1.8x. Most of the gain comes from the hasher.

## Tests and proof

- New tests in `playnyu/tests.py`: the test run uses `MD5PasswordHasher`; a subprocess with `sys.argv` set to `runserver`, `gunicorn` or `migrate` keeps Django's default hashers.
- Full suite passes serial and parallel, on SQLite and (if available) on local Postgres.
- Local timings, each with `time`: baseline serial; fast hasher serial; fast hasher `--parallel auto`; coverage parallel run plus `combine` plus `report`. Record `--durations 20` once.
- Travis: compare build 241's two jobs with the PR build's two jobs (per-step times from the job logs). Comment both on #267.
- Rollback: three commits (hasher, parallel, Travis `if:`). Revert any one alone.
