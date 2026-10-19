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

## Configuration (environment variables)

| Variable | Default | Notes |
|---|---|---|
| `DJANGO_DEBUG` | `True` | Set to `False` on AWS |
| `DJANGO_SECRET_KEY` | dev-only key (only when debug is on) | Required when `DJANGO_DEBUG=False` |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated; add the AWS hostname |

## Project layout

```
manage.py
playnyu/    project settings and root URLs
core/       starter app (home page and health check)
```

Database: SQLite for now (`db.sqlite3`, not committed).
