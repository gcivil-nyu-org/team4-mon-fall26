# Sport period defaults on new databases (#262)

## Intent

Migration `teams/migrations/0014_sport_period_defaults.py` sets periods for known sports by name. On a fresh database it runs before any sport exists. `seed_league_data` then creates the sports (`.ebextensions/django.config`, step `03d`), and each sport gets the model default, 4 "Q". A fresh local DB showed Futsal as 4 Q. Production and the testing site had their sports before 0014 ran, so their values are correct.

`seed_match_details` splits scores over `Sport.period_count`. `seed_class_league` relies on the same values. With wrong periods, Futsal gets 4 quarters. `matches/test_seed_match_details.py` patches the periods by hand to work around this.

## Goals

- `seed_league_data` creates each sport with the 0014 periods: Basketball 4 Q, Soccer and Futsal 2 Half, Volleyball 5 Set, Flag football 4 Q, Ultimate and Ultimate frisbee 2 Half.
- A sport created on the manage sports page or in Django admin gets the same periods when the creator leaves the period fields blank.
- One app mapping holds these values. A test keeps migration 0014's frozen copy equal to it.
- A one-off command fixes environments that already have the wrong values.

## Non-goals

- No change to existing sports, on deploy or on edit.
- No change to migration 0014 behavior, and no new data migration.
- No new sports, and no change to the model field defaults (4, "Q").
- No change to `seed_match_details` or `seed_class_league`. Their test workarounds stay.

## Approaches

**A. Form and seed apply the defaults (recommended).** A new module `teams/sport_defaults.py` holds `SPORT_PERIODS` and `default_periods(name)`. `seed_league_data` passes the periods to `Sport.objects.create`. `SportForm` fills blank period fields from the mapping for a new sport only. The manage sports page and `SportAdmin` both use `SportForm`, so one change covers both pages. The form knows whether the creator chose a value; the model does not.

**B. `Sport.save` applies the defaults when `pk is None`.** This covers every creation path, including the shell. But the model cannot tell "creator chose 4 Q" from "field left at its default". So a deliberate 4 Q Soccer becomes 2 Half. About 60 test fixtures create `Sport(name="Soccer")` and expect 4 Q; for example, `EditSportViewTests.test_edit_sport_shows_errors` asserts 4. These would change silently.

**C. A `pre_save` signal.** This has the same problem as B, and the behavior is harder to find.

Recommendation: A. Explicit call sites cost one line each, and the creator's choice always wins.

## Rules

1. `teams/sport_defaults.py` holds `DEFAULT_PERIODS = (4, "Q")` and `SPORT_PERIODS`. Keys are `name_key(name)` from `teams/catalog_rules.py`.
2. `default_periods(name)` returns the mapping value, or `DEFAULT_PERIODS` for an unknown name.
3. Migration 0014 keeps its own `PERIODS` copy. Migrations must not import app code that changes. A test asserts that `0014.PERIODS == SPORT_PERIODS` and `0014.DEFAULT == DEFAULT_PERIODS`.
4. `seed_league_data` sets periods only on the sports it creates. It never reads or changes an existing sport.
5. `SportForm` with a new instance (`instance.pk is None`):
   - It shows the period fields blank, not prefilled with 4 and Q.
   - A blank field takes its value from `default_periods(name)`. Each field is filled separately.
   - A value the creator typed always wins, also 4 or Q.
6. `SportForm` with an existing instance keeps the current behavior: a blank field keeps the stored value.
7. `fix_sport_periods [--dry-run]` is a manual command. It changes a sport only when all of these are true:
   - its name is in `SPORT_PERIODS`, and the mapping value is not `DEFAULT_PERIODS`;
   - its stored values are exactly `DEFAULT_PERIODS`;
   - no `MatchPeriodScore` exists for a match of that sport.
   It reports each sport it fixes or skips, with the reason. `--dry-run` writes nothing.
8. The fix-up command is not added to `.ebextensions`. A person runs it once where needed.

### Why a command, not a data migration

A data migration runs everywhere without review. It cannot tell a wrong default from an admin's deliberate 4 Q. The command shows what it will change (`--dry-run`), runs only where a person chooses, and skips sports with custom values.

### Fit with #228

`Sport.clean` blocks a new `period_count` once a match of the sport has period scores. The command skips those sports before it saves, and it reports "period scores stored". It never deletes or relabels scores. A dev DB in that state needs a reset or a manual fix; that is out of scope.

## Tests

- **Fresh DB:** a `TestCase` database is built by migrations with no sports. `call_command("seed_league_data")` then gives each of the 9 sports its expected periods. Cricket, Pickleball and Softball get 4 Q.
- **Seed keeps existing sports:** a pre-made `Soccer` at (3, "Q") stays (3, "Q") after the seed.
- **Mapping:** the frozen 0014 copy equals `SPORT_PERIODS`. `default_periods` ignores case and spacing, and returns 4 Q for unknown names.
- **Manage sports page:** a post of "Futsal" with blank periods gives 2 Half. A post with 4 and Q kept gives 4 Q. A post with count 3 and a blank label gives (3, "Half"). The unbound form shows blank period fields.
- **Edit sport:** blank periods on an existing Soccer keep (4, "Q").
- **Django admin:** an add of "Volleyball" with blank periods gives 5 Set.
- **fix_sport_periods:** it fixes a 4 Q Futsal. It keeps a custom value, an unknown sport and Basketball. It skips a sport with period scores. `--dry-run` writes nothing.

## Decisions

The user approved each recommendation on 2026-11-16.

1. **Migration 0014 keeps its frozen copy.** It does not import the app mapping. `test_migration_copy_matches_app_mapping` keeps the two copies equal. The PR says this, so the reviewer reads issue criterion 2 as met.
2. **`fix_sport_periods` runs by hand only.** Run `--dry-run` first, then run it for real only if it lists sports to fix. It is not a deploy step.
3. **No `--force` option.** #228 exists to stop relabeled scores, and only dev DBs can be in that state.
