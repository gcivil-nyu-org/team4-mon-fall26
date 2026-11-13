# Default semester seasons per sport

## Intent

Each semester, PlayNYU creates one season per sport with default divisions. Players always find a league to join. League Admins don't set up the same leagues by hand each term. Pages like schedule and standings have real seasons to show.

## Goals

- One default season per sport, per semester (Fall and Spring).
- Default divisions in each: University-wide, CAS, Tandon, Stern, Steinhardt, Tisch, Inter-school.
- Created automatically on every deploy. The command only adds what is missing.
- League Admins can still create custom seasons (for example, a clubs league), with or without a sport.

## Non-goals

- No school field on profiles. Divisions use the honour system.
- No automatic state changes after creation. League Admins still move seasons to active and closed.
- No demo teams or matches. That is separate work.
- No Summer semester.

## Approaches

- **A. One season per sport per semester (picked).** Add an optional `Season.sport`. Standings stay one table per season, so each table holds one sport.
- B. One season per semester, with sport × school divisions. About 54 divisions per season, and standings would mix sports.
- C. A new League model above seasons. Too large a change for the benefit.

The user picked A because standings compute one table per season (`matches/standings.py`).

## Design

### Model (`teams/models.py`)

- `Season.sport`: optional FK to `Sport` (`PROTECT`, `related_name="seasons"`). Blank means "any sport" (custom leagues, old seasons).
- `Season.term`: `CharField(max_length=20, blank=True)`, for example `"2026-fall"`. Only default seasons set it.
- Unique constraint on (`sport`, `term`) when `term` is not blank. The command uses this key, so an admin can rename a default season without a duplicate.

### Sport rules

- A team in a season with a sport must play that sport (`Team.clean`, and `TeamCreateForm` shows the error on the field).
- A free agent request in a season with a sport must ask for that sport (`FreeAgentRequest.clean`).
- `SeasonForm` gets an optional sport field. Changing it is refused when a team of another sport is already in the season.
- "One team per player per season" stays as it is. With per-sport seasons, a player can join one team per sport each semester.

### Seeding (`teams/management/commands/seed_semester_seasons.py`)

- Semesters: Fall runs Sep 1 to Dec 15. Spring runs Jan 20 to May 10.
- The current semester is the one whose dates contain today. Between semesters, it is the next one to start.
- For each `Sport`, make sure the current semester's season exists (state open) and the next semester's season exists (state draft).
- Name: `"<Term> <Year> <Sport>"`, for example `"Fall 2026 Basketball"`.
- Create the default divisions in a new season only. Do not change existing seasons, their states or their divisions.
- Accept `--today YYYY-MM-DD` for tests and local checks.
- `.ebextensions/django.config` runs it after `seed_league_data`.

## Left to the builder

- Wording of error messages and help text.
- Test layout, following the existing `teams/test_*.py` style.
