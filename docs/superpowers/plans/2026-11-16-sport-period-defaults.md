# Sport period defaults Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** New databases, and sports created by name, get the migration 0014 periods for each known sport (#262).

**Architecture:** A new `teams/sport_defaults.py` holds the app mapping. `seed_league_data` and `SportForm` (new sport only) read it, and `SportForm` covers the manage sports page and `SportAdmin`. Migration 0014 keeps its frozen copy, and a test keeps the two copies equal. A manual `fix_sport_periods [--dry-run]` command fixes databases that already have the wrong values.

**Tech Stack:** Django, the Django test runner, coverage, black, flake8.

**Spec:** `docs/superpowers/specs/2026-11-16-sport-period-defaults-design.md`

## Global Constraints

- Branch: `nihal/roles-and-sport-periods`, from `origin/testing`. If it does not exist: `git fetch origin && git checkout -b nihal/roles-and-sport-periods origin/testing`. Else `git switch nihal/roles-and-sport-periods`. Do not commit to `main` or `testing`.
- The branch also carries #261 (roles page) from another plan. Do not edit #261 files. Do not depend on #261 code. If a merge conflict touches a shared file, keep both changes.
- Commit messages start with `#262: `. They have no Claude co-author line or footer.
- No GitHub issue, ZenHub or PR steps in this plan.
- Do not edit `teams/migrations/0014_sport_period_defaults.py`. Add no migration. Do not change the model field defaults (4, "Q").
- Mapping values, keyed by `name_key`: `basketball` (4, "Q"), `soccer` (2, "Half"), `futsal` (2, "Half"), `volleyball` (5, "Set"), `flag football` (4, "Q"), `ultimate` (2, "Half"), `ultimate frisbee` (2, "Half"). Default: (4, "Q").
- A period value that the creator types always wins. Existing sports never change, except through `fix_sport_periods`.
- CI: `black --check .`, `flake8 .`, `coverage run manage.py test`, `coverage report --fail-under=80`, `python manage.py makemigrations --check --dry-run`.

## Review Focus

1. **Odd spelling.** An admin adds "  FUTSAL " or "Ultimate Frisbee". It gets 2 Half, the same as "Futsal" (Task 1, Task 3).
2. **Prefilled add form.** The admin add page and the manage sports page used to show 4 and Q. An admin who submits only a name must get the sport's periods, so the new form must render blank fields (Task 3).
3. **Half a choice.** The creator types count 3 for Soccer and leaves the label blank. Result: (3, "Half"); each blank field is filled separately (Task 3).
4. **Bad name, blank periods.** A post with an empty name shows the name error and does not crash on the period lookup (Task 3).
5. **Stored period scores.** `fix_sport_periods` meets a 4 Q Soccer with period scores. It skips the sport with a reason and does not raise the #228 `ValidationError` (Task 4).

---

## File structure

| File | Change | Responsibility |
|---|---|---|
| `teams/sport_defaults.py` | Create | `DEFAULT_PERIODS`, `SPORT_PERIODS`, `default_periods(name)` |
| `teams/management/commands/seed_league_data.py` | Modify | Create sports with their default periods |
| `teams/forms.py` (`SportForm`) | Modify | New sport: blank period fields, filled from the mapping |
| `teams/management/commands/fix_sport_periods.py` | Create | One-off fix-up, with `--dry-run` |
| `teams/test_sport_defaults.py` | Create | All #262 tests |

`teams/admin.py` and `teams/views.py` need no change: both pages use `SportForm`.

---

### Task 1: The shared mapping

**Files:**
- Create: `teams/sport_defaults.py`
- Test: `teams/test_sport_defaults.py`

**Interfaces:**
- Consumes: `teams.catalog_rules.name_key(name: str) -> str`.
- Produces:
  - `DEFAULT_PERIODS: tuple[int, str] = (4, "Q")`
  - `SPORT_PERIODS: dict[str, tuple[int, str]]`, keyed by `name_key`, with the values in Global Constraints.
  - `default_periods(name: str) -> tuple[int, str]`: the mapping value for `name_key(name or "")`, else `DEFAULT_PERIODS`.

- [ ] **Step 1: Write the failing tests** in `teams/test_sport_defaults.py`, class `SportDefaultsTests(SimpleTestCase)`:

```python
period_migration = importlib.import_module("teams.migrations.0014_sport_period_defaults")

def test_migration_copy_matches_app_mapping(self):
    self.assertEqual(period_migration.PERIODS, SPORT_PERIODS)
    self.assertEqual(period_migration.DEFAULT, DEFAULT_PERIODS)

def test_default_matches_model_fields(self):
    fields = Sport._meta
    self.assertEqual(
        (fields.get_field("period_count").default, fields.get_field("period_label").default),
        DEFAULT_PERIODS,
    )

def test_known_names_ignore_case_and_spacing(self):
    self.assertEqual(default_periods("  FUTSAL "), (2, "Half"))
    self.assertEqual(default_periods("Ultimate   Frisbee"), (2, "Half"))
    self.assertEqual(default_periods("volleyball"), (5, "Set"))

def test_unknown_or_blank_name_gets_default(self):
    self.assertEqual(default_periods("Cricket"), (4, "Q"))
    self.assertEqual(default_periods(""), (4, "Q"))
```

- [ ] **Step 2: Run the tests and make sure they fail**

Run: `python manage.py test teams.test_sport_defaults`
Expected: FAIL, `ModuleNotFoundError: No module named 'teams.sport_defaults'`.

- [ ] **Step 3: Implement `teams/sport_defaults.py`**

Module docstring: one line saying migration 0014 keeps a frozen copy and `test_migration_copy_matches_app_mapping` keeps them equal. Import only `teams.catalog_rules`, never `teams.models`.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `python manage.py test teams.test_sport_defaults`
Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add teams/sport_defaults.py teams/test_sport_defaults.py
git commit -m "#262: Add the shared sport period mapping"
```

---

### Task 2: seed_league_data creates sports with their periods

**Files:**
- Modify: `teams/management/commands/seed_league_data.py` (the `Sport.objects.create(name=name)` line in `handle`)
- Test: `teams/test_sport_defaults.py`

**Interfaces:**
- Consumes: `default_periods(name)` from Task 1.
- Produces: no new names.

- [ ] **Step 1: Write the failing tests**, class `SeedLeagueDataPeriodsTests(TestCase)`. The test database is built by migrations with no sports, so it is a fresh database.

```python
EXPECTED = {
    "Basketball": (4, "Q"), "Cricket": (4, "Q"), "Flag football": (4, "Q"),
    "Futsal": (2, "Half"), "Pickleball": (4, "Q"), "Soccer": (2, "Half"),
    "Softball": (4, "Q"), "Ultimate frisbee": (2, "Half"), "Volleyball": (5, "Set"),
}

def test_fresh_database_gets_each_sports_periods(self):
    self.assertFalse(Sport.objects.exists())
    call_command("seed_league_data", stdout=StringIO())
    self.assertEqual(
        {s.name: (s.period_count, s.period_label) for s in Sport.objects.all()},
        EXPECTED,
    )

def test_existing_sport_keeps_its_periods(self):
    Sport.objects.create(name="Soccer", period_count=3, period_label="Q")
    call_command("seed_league_data", stdout=StringIO())
    soccer = Sport.objects.get(name="Soccer")
    self.assertEqual((soccer.period_count, soccer.period_label), (3, "Q"))
```

- [ ] **Step 2: Run the tests and make sure the first fails**

Run: `python manage.py test teams.test_sport_defaults.SeedLeagueDataPeriodsTests`
Expected: `test_fresh_database_gets_each_sports_periods` FAILS (Futsal is (4, "Q")). The second test passes already; it guards rule 4.

- [ ] **Step 3: Pass the periods on create**

`count, label = default_periods(name)`, then `Sport.objects.create(name=name, period_count=count, period_label=label)`. Add one line to the module docstring: new sports get their periods from `teams/sport_defaults.py`; existing sports are not changed.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `python manage.py test teams.test_sport_defaults teams.test_seed_league_data`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add teams/management/commands/seed_league_data.py teams/test_sport_defaults.py
git commit -m "#262: Seed new sports with their default periods"
```

---

### Task 3: A new sport on the manage sports page or in admin gets its periods

**Files:**
- Modify: `teams/forms.py` (`SportForm.__init__`, `_keep_current`, `help_texts`)
- Test: `teams/test_sport_defaults.py`

**Interfaces:**
- Consumes: `default_periods(name)` from Task 1.
- Produces: no new public names. Behavior: for `instance.pk is None`, the period fields render blank, and a blank field takes `default_periods(cleaned name)`. For an existing instance, a blank field keeps the stored value (no change).

- [ ] **Step 1: Write the failing tests**, class `NewSportPeriodsTests(TestCase)`. Use `make_user("admin", admin=True)` from `matches.tests` for the manage page, and `create_superuser` for admin (see `teams/test_default_seasons.py:SportAdminCreatesSeasonsTests`). Helper `periods(name)` returns `(period_count, period_label)` of the stored sport.

```python
def test_new_form_shows_blank_period_fields(self):
    form = SportForm()
    self.assertIsNone(form["period_count"].value())
    self.assertIsNone(form["period_label"].value())

def test_edit_form_shows_stored_periods(self):
    sport = Sport.objects.create(name="Soccer", period_count=2, period_label="Half")
    form = SportForm(instance=sport)
    self.assertEqual((form["period_count"].value(), form["period_label"].value()), (2, "Half"))

def test_manage_page_blank_periods_use_sport_defaults(self):
    # login as League Admin
    self.client.post(reverse("teams:manage_sports"), {"name": "  FUTSAL "})
    self.assertEqual(self.periods("FUTSAL"), (2, "Half"))

def test_manage_page_typed_periods_win(self):
    self.client.post(reverse("teams:manage_sports"),
                     {"name": "Soccer", "period_count": 4, "period_label": "Q"})
    self.assertEqual(self.periods("Soccer"), (4, "Q"))

def test_each_blank_field_is_filled_on_its_own(self):
    self.client.post(reverse("teams:manage_sports"),
                     {"name": "Soccer", "period_count": 3, "period_label": ""})
    self.assertEqual(self.periods("Soccer"), (3, "Half"))

def test_unknown_sport_gets_model_default(self):
    self.client.post(reverse("teams:manage_sports"), {"name": "Rugby"})
    self.assertEqual(self.periods("Rugby"), (4, "Q"))

def test_blank_name_shows_error(self):
    response = self.client.post(reverse("teams:manage_sports"), {"name": ""})
    self.assertEqual(response.status_code, 200)
    self.assertFalse(Sport.objects.exists())

def test_edit_with_blank_periods_keeps_stored_values(self):
    sport = Sport.objects.create(name="Soccer")  # (4, "Q")
    self.client.post(reverse("teams:edit_sport", args=[sport.pk]),
                     {"name": "Soccer", "period_count": "", "period_label": ""})
    self.assertEqual(self.periods("Soccer"), (4, "Q"))

def test_admin_add_blank_periods_use_sport_defaults(self):
    # login as superuser
    self.client.post(reverse("admin:teams_sport_add"), {"name": "Volleyball"})
    self.assertEqual(self.periods("Volleyball"), (5, "Set"))
```

- [ ] **Step 2: Run the tests and make sure they fail**

Run: `python manage.py test teams.test_sport_defaults.NewSportPeriodsTests`
Expected: FAIL in `test_new_form_shows_blank_period_fields`, `test_manage_page_blank_periods_use_sport_defaults`, `test_each_blank_field_is_filled_on_its_own` and `test_admin_add_blank_periods_use_sport_defaults`. The other tests pass already and guard behavior that must not change.

- [ ] **Step 3: Change `SportForm`**

- In `__init__`: when `self.instance.pk is None`, set `self.initial["period_count"]` and `self.initial["period_label"]` to `None`. Keep the explicit-`initial=` argument working: clear a key only when the caller did not pass it.
- In `_keep_current(name)`: for a blank value on a new instance, return the matching item of `default_periods(self.cleaned_data.get("name", ""))` (index 0 for `period_count`, 1 for `period_label`). On an existing instance, keep the current `getattr(self.instance, name)`. `name` is declared first in `Meta.fields`, so it is cleaned before the period fields.
- Help text for `period_count`: "Leave blank for the usual count of a known sport (Soccer: 2), else 4. Use 0 for a sport with no periods." Help text for `period_label`: "Leave blank for the usual label (Soccer: Half), else Q. Q gives Q1, Q2. Half gives Half 1, Half 2."
- Update the `__init__` comment: a blank field on a new sport takes the sport's default periods; on an existing sport it keeps the stored value.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `python manage.py test teams.test_sport_defaults teams.test_sport_periods teams.test_default_seasons teams.test_league_setup`
Expected: PASS. `test_sport_periods.EditSportViewTests.test_add_sport_without_period_fields_uses_defaults` (Rugby, 4 Q) still passes.

- [ ] **Step 5: Commit**

```bash
git add teams/forms.py teams/test_sport_defaults.py
git commit -m "#262: Give new sports their default periods on the sport forms"
```

---

### Task 4: fix_sport_periods fixes databases that already have the wrong values

**Files:**
- Create: `teams/management/commands/fix_sport_periods.py`
- Test: `teams/test_sport_defaults.py`

**Interfaces:**
- Consumes: `SPORT_PERIODS`, `DEFAULT_PERIODS`, `name_key`. `MatchPeriodScore` through `apps.get_model("matches", "MatchPeriodScore")`, filtered on `match__home_team__sport=sport` (the same query as `Sport.clean`).
- Produces: `python manage.py fix_sport_periods [--dry-run]`.

Rules, per sport in name order. `periods(name)` in the tests returns the stored `(period_count, period_label)`:

| Condition | Action | Output line |
|---|---|---|
| Name not in `SPORT_PERIODS`, or mapping value is `DEFAULT_PERIODS` | none | no line |
| Stored values already equal the mapping value (added in the build) | none | no line, not counted |
| Stored values are not `DEFAULT_PERIODS` | none | `{name}: kept ({count} {label}, set by an admin).` |
| A period score exists for the sport | none | `{name}: skipped (period scores stored).` |
| Else | set the mapping value with `sport.save(update_fields=["period_count", "period_label"])` | `{name}: fixed to {count} {label}.` (dry run: `would fix to`) |

Last line: `Fixed {n}, kept {k}, skipped {s}.` With `--dry-run`, prefix it with `Dry run: ` and write nothing. The command module docstring says: run once by hand where sports were created after migration 0014; not a deploy step.

- [ ] **Step 1: Write the failing tests**, class `FixSportPeriodsTests(MatchFixtures)` from `matches.tests`. `MatchFixtures` makes `self.soccer` (4, "Q") and `self.hoops` (Basketball). Helper `run(*args)` returns stdout from `call_command("fix_sport_periods", *args, stdout=out)`.

```python
def test_fixes_default_valued_known_sport(self):
    futsal = Sport.objects.create(name="Futsal")
    output = self.run()
    futsal.refresh_from_db()
    self.assertEqual((futsal.period_count, futsal.period_label), (2, "Half"))
    self.assertIn("Futsal: fixed to 2 Half.", output)

def test_keeps_custom_values_unknown_sports_and_basketball(self):
    Sport.objects.create(name="Volleyball", period_count=3, period_label="Set")
    Sport.objects.create(name="Rugby")
    output = self.run()
    self.assertEqual(periods("Volleyball"), (3, "Set"))
    self.assertEqual(periods("Rugby"), (4, "Q"))
    self.assertEqual(periods("Basketball"), (4, "Q"))
    self.assertIn("Volleyball: kept (3 Set, set by an admin).", output)
    self.assertNotIn("Rugby", output)

def test_skips_sport_with_period_scores(self):
    match = self.build(); match.save()
    MatchPeriodScore.objects.create(match=match, period=1, home_points=1, away_points=0)
    output = self.run()
    self.assertEqual(periods("Soccer"), (4, "Q"))
    self.assertIn("Soccer: skipped (period scores stored).", output)

def test_dry_run_writes_nothing(self):
    Sport.objects.create(name="Futsal")
    output = self.run("--dry-run")
    self.assertEqual(periods("Futsal"), (4, "Q"))
    self.assertIn("Futsal: would fix to 2 Half.", output)
    # self.soccer is also a 4 Q Soccer with no period scores, so 2 fixes.
    self.assertIn("Dry run: Fixed 2, kept 0, skipped 0.", output)
```

- [ ] **Step 2: Run the tests and make sure they fail**

Run: `python manage.py test teams.test_sport_defaults.FixSportPeriodsTests`
Expected: FAIL, `CommandError: Unknown command: 'fix_sport_periods'`.

- [ ] **Step 3: Implement the command** with the rules in the table above. Check period scores before the save, so `Sport.clean` never raises.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `python manage.py test teams.test_sport_defaults`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add teams/management/commands/fix_sport_periods.py teams/test_sport_defaults.py
git commit -m "#262: Add fix_sport_periods for databases seeded after migration 0014"
```

---

### Task 5: CI checks

**Files:** none, unless a check fails.

- [ ] **Step 1: Format and lint**

Run: `black --check . && flake8 .`
Expected: no output from flake8; black reports all files unchanged. If black fails, run `black .` on the #262 files only.

- [ ] **Step 2: Full test suite with coverage**

Run: `coverage run manage.py test && coverage report --fail-under=80`
Expected: all tests pass; total coverage at least 80%.

- [ ] **Step 3: No missing migrations**

Run: `python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

- [ ] **Step 4: Fresh local database check**

Run: `rm -f /private/tmp/sport-periods.sqlite3 && DATABASE_URL=sqlite:////private/tmp/sport-periods.sqlite3 python manage.py migrate --noinput && DATABASE_URL=sqlite:////private/tmp/sport-periods.sqlite3 python manage.py seed_league_data && DATABASE_URL=sqlite:////private/tmp/sport-periods.sqlite3 python manage.py shell -c "from teams.models import Sport; print(sorted(Sport.objects.values_list('name','period_count','period_label')))"`
Expected: Futsal and Soccer `2, 'Half'`, Volleyball `5, 'Set'`, Ultimate frisbee `2, 'Half'`, others `4, 'Q'`. `playnyu/settings.py` reads `DATABASE_URL` through `database_config`; if it rejects a `sqlite:` URL, skip this step, because Task 2 covers it.

- [ ] **Step 5: Commit fixes, if any**

```bash
git add <fixed files>
git commit -m "#262: Fix lint"
```

---

## Changes during the build

- Task 3: two more tests. `test_explicit_initial_is_kept` covers the `initial=` rule. `test_blank_name_shows_error` also checks the name error.
- Task 4: the test helper is `run_command`, not `run`. `run` replaces `unittest.TestCase.run`, and no test runs.
- Task 4: a sport that already has its mapping value gets no line and no count. The table said "kept (2 Half, set by an admin)", which is false for that sport. The fresh DB dry run found this.
- Task 4: the command runs in one `transaction.atomic()` block.
- Task 5: the fresh DB check uses a file in the session scratchpad, not `/private/tmp/sport-periods.sqlite3`.
