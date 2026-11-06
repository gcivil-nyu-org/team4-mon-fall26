# Database

The app reads `DATABASE_URL` from the environment.

| Where | `DATABASE_URL` | Database | Data after a deploy |
|---|---|---|---|
| Local development | Unset | SQLite (`db.sqlite3`) | Not affected |
| Testing and production | Set with `eb setenv` | Postgres on RDS | Kept |

If `DATABASE_URL` is unset on AWS, the site still runs on SQLite and loses its data on every deploy.

`.ebextensions/django.config` runs `migrate` on every deploy. If the database can't be reached, the migration fails and so does the deploy.

## Set up an environment

Do this once for `playnyu-test`, then once for `playnyu-prod`. Each environment gets its own database. Set up testing and check it before you merge to `main`.

1. **Create the database.** In the RDS console, in `us-east-2`, create a PostgreSQL instance:
   - Create it in RDS, not from the Elastic Beanstalk console. A database that Elastic Beanstalk creates is tied to the environment and can be deleted with it.
   - Use the same VPC as the environment. Set **Public access** to No.
   - Set **Initial database name** to `playnyu`.
   - Use an engine version that [Django supports](https://docs.djangoproject.com/en/6.1/ref/databases/#postgresql-notes).
   - Keep automated backups on. Turn on deletion protection for production.
2. **Allow the connection.** In the database's security group, add an inbound rule for PostgreSQL (port 5432). Set the source to the security group of the environment's EC2 instances. Do not allow `0.0.0.0/0`.
3. **Set the variable before you merge or deploy this code.** The older code ignores the variable, so setting it first is safe. The next deploy then installs the driver and runs the migrations on the new database.

   ```bash
   eb setenv -e playnyu-test DATABASE_URL='postgres://USER:PASSWORD@ENDPOINT:5432/playnyu?sslmode=require'
   ```

   If the password has characters like `@`, `/`, `:` or `#`, percent-encode them. For example, `@` becomes `%40`.
4. **Deploy.** Travis deploys when the change reaches `testing` (or `main` for production). If the code is already deployed when you set the variable, deploy again so the migrations run.
5. **Check that data survives.** Sign in, create something (a team, for example), and deploy again. It should still be there.

Never put the URL or password in the repo, a PR, an issue or a chat.

## What changes when data persists

- **Old data is not copied.** The new database starts empty, and the first deploy creates the tables and accounts.
- **Migrations run on real data.** Test a migration against existing rows, and plan how to fix it if it fails. Deleting the database is no longer a normal fix.
- **Accounts:**
  - `DJANGO_SUPERUSER_*` only creates the admin on the first deploy. Changing the password variable later has no effect. Use `python manage.py changepassword` or the admin site instead.
  - `TEST_PLAYER_*` and `DEMO_USERS_PASSWORD` accounts have their password and active status reset on every deploy. Their teams and other data stay.

## Go back to SQLite

Remove the variable: `eb setenv -e playnyu-test DATABASE_URL=`. The site goes back to SQLite and to losing data on each deploy. The RDS data stays until you delete the instance.

## Run on Postgres locally

Run this when you use `select_for_update`, raw SQL or anything else that depends on the database. SQLite ignores `select_for_update`, so some queries that pass on SQLite fail on Postgres. Travis only tests on SQLite.

```bash
DATABASE_URL='postgres://USER:PASSWORD@localhost:5432/playnyu' python manage.py test
```

Use `select_for_update(of=("self",))` when the query also uses `select_related` on a nullable field. Otherwise Postgres rejects it with "FOR UPDATE cannot be applied to the nullable side of an outer join".
