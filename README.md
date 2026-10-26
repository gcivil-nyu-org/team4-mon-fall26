# team4-mon-fall26 (PlayNYU)

Django project for Team 4.

## Links
- Prod: http://playnyu-prod.eba-ax4phmwp.us-east-2.elasticbeanstalk.com/

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

Every push and pull request runs `flake8`, the tests and a coverage check (`.travis.yml`).
When the build passes, a push to `testing` deploys to the testing environment and a push to
`main` deploys to production (`playnyu-prod`, us-east-2). Pull request builds never deploy.

Run the same checks locally:

```bash
pip install -r requirements-dev.txt
flake8 .
coverage run manage.py test && coverage report
```

Travis needs these variables (Settings > Environment Variables, "Display value in build log" off):

| Variable | Used for |
|---|---|
| `AWS_ACCESS_KEY_ID_PROD`, `AWS_SECRET_ACCESS_KEY_PROD` | Deploy to production |
| `AWS_ACCESS_KEY_ID_TESTING`, `AWS_SECRET_ACCESS_KEY_TESTING` | Deploy to testing |
| `EB_REGION_TESTING`, `EB_APP_TESTING`, `EB_ENV_TESTING`, `EB_BUCKET_TESTING` | Testing environment details |

## Configuration (environment variables)

| Variable | Default | Notes |
|---|---|---|
| `DJANGO_DEBUG` | `True` | Set to `False` on AWS |
| `DJANGO_SECRET_KEY` | dev-only key (only when debug is on) | Required when `DJANGO_DEBUG=False` |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated; add the AWS hostname |
| `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | unset (emails print to the console) | Set to send real verification emails over SMTP |
| `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_EMAIL`, `DJANGO_SUPERUSER_PASSWORD` | unset | Admin user created on each deploy |

## Project layout

```
manage.py
playnyu/    project settings and root URLs
core/       starter app (home page and health check)
```

Database: SQLite for now (`db.sqlite3`, not committed).
