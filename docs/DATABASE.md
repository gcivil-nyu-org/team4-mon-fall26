# Database

The app reads `DATABASE_URL` from the environment.

| Where | `DATABASE_URL` | Database | Data after a deploy |
|---|---|---|---|
| Local development | Unset | SQLite (`db.sqlite3`) | Not affected |
| Testing and production | Set with `eb setenv` | Postgres on [Neon](https://neon.com) | Kept |

If `DATABASE_URL` is unset on AWS, the site still runs on SQLite and loses its data on every deploy.

`.ebextensions/django.config` runs `migrate` on every deploy. If the database can't be reached, the migration fails and so does the deploy.

## Set up an environment

Do this once for `playnyu-test`, then once for `playnyu-prod`. Set up testing and check it before you merge to `main`.

1. **Create a Neon project.** Use one project for each environment, named `playnyu-test` and `playnyu-prod`, so testing data never mixes with production data.
   - Region: AWS US East 2 (Ohio), the same region as Elastic Beanstalk.
   - Postgres version: 15 or newer. [Django 6.1 needs 15 or newer.](https://docs.djangoproject.com/en/6.1/ref/databases/#postgresql-notes)
2. **Copy the direct connection string.** In the project's **Connect** dialog, turn off connection pooling. The host should not contain `-pooler`. The app keeps each connection open for up to 60 seconds, and Neon's pooled connection doesn't support that setup.
3. **Set the variable.** Copy the whole string, including `?sslmode=require`:

   ```bash
   eb setenv DATABASE_URL='postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require' -e playnyu-test
   ```

   Keep the quotes, because the shell treats `?` and `&` as special characters. If you build the string yourself and the password has characters like `@`, `/`, `:` or `#`, percent-encode them. For example, `@` becomes `%40`.
4. **Deploy.** Travis deploys when a change reaches `testing` (or `main` for production). If nothing new is waiting to deploy, run `eb deploy playnyu-test` from an up-to-date `testing` checkout so the migrations run.
5. **Check that data survives.** Sign in, create something (a team, for example), and deploy again. It should still be there.

Never put the connection string or password in the repo, a PR, an issue or a chat.

## Neon free plan

- The free plan doesn't charge for going over a limit. Instead, writes that need more storage fail until you free space or upgrade. Check the current limits in [Neon's free plan FAQ](https://neon.com/faqs/free-plan-limits-and-quotas).
- After about 5 minutes with no queries, Neon pauses the database. The first request after that takes a moment longer while it wakes up.

## What changes when data persists

- **Old data is not copied.** The new database starts empty, and the first deploy creates the tables, accounts, sports and facilities.
- **Migrations run on real data.** Test a migration against existing rows, and plan how to fix it if it fails. Deleting the database is no longer a normal fix.
- **Accounts:**
  - `DJANGO_SUPERUSER_*` only creates the admin on the first deploy. Changing the password variable later has no effect. Use `python manage.py changepassword` or the admin site instead.
  - `TEST_PLAYER_*` and `DEMO_USERS_PASSWORD` accounts have their password and active status reset on every deploy. Their teams and other data stay.
- **Seed data:** `seed_league_data` only adds sports and the demo season when they are missing. `seed_semester_seasons` only adds this and next semester's season for each sport when they are missing; it never changes existing seasons or their divisions. `seed_facilities` updates the seeded facilities on every deploy, so admin changes to them (for example, deactivating one) are undone at the next deploy.

## Go back to SQLite

Remove the variable: `eb setenv DATABASE_URL= -e playnyu-test`. The site goes back to SQLite and to losing data on each deploy. The data in Neon stays until you delete the project.

## Postgres in CI and locally

Travis runs the tests twice: on SQLite with coverage, and on Postgres. SQLite ignores `select_for_update`, so some queries pass on SQLite and fail on Postgres. Only the SQLite job deploys.

To run the tests on Postgres locally:

```bash
DATABASE_URL='postgres://USER:PASSWORD@localhost:5432/playnyu' python manage.py test
```

Use `select_for_update(of=("self",))` when the query also uses `select_related` on a nullable field. Otherwise Postgres rejects it with "FOR UPDATE cannot be applied to the nullable side of an outer join".
