# team4-mon-fall26 (PlayNYU)

Django project for Team 4.

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

## Configuration (environment variables)

| Variable | Default | Notes |
|---|---|---|
| `DJANGO_DEBUG` | `True` | Set to `False` on AWS |
| `DJANGO_SECRET_KEY` | dev-only key (only when debug is on) | Required when `DJANGO_DEBUG=False` |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated; add the AWS hostname |
| `DJANGO_DEFAULT_FROM_EMAIL` | `PlayNYU <noreply@playnyu.local>` | Sender shown on confirmation emails |

## Accounts: registration and NYU verification (Epic #1)

- `/accounts/register/`: sign up with an `@nyu.edu` email. Any other address shows "Please use your NYU ID".
- A valid NYU email creates an **inactive** account and sends a confirmation link to that address.
  The link works once and expires after 3 days (Django's `PASSWORD_RESET_TIMEOUT`).
- Until the link is clicked the account cannot log in. A fake or mistyped address never gets the
  email, so that account stays unverified. `/accounts/resend/` sends a new link.
- Verified users log in at `/accounts/login/` with their NYU email, then can edit their profile.
- Because only verified accounts are active, the team captain's add-player form accepts only verified players.

**Emails during development and on AWS:** the project uses Django's console email backend, so the
confirmation email is **printed to the server log** instead of being sent. Locally, look in the
terminal that runs `runserver`. On Elastic Beanstalk, run `eb logs` and search for
`Confirmation link for`. That log line holds the whole link on one line (the printed email wraps it
in two, so copy the link from the log line, not from the email).
Sending real email (for example Amazon SES) is a settings change in `MAILERS`; the log line is
written only while the console backend is in use.

## Project layout

```
manage.py
playnyu/    project settings and root URLs
core/       starter app (home page and health check)
accounts/   registration, NYU email verification, login
teams/      teams, captain adds players, roster
profiles/   edit profile
```

Database: SQLite for now (`db.sqlite3`, not committed).
