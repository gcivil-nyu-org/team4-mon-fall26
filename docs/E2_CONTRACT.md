# E2 contract: sports, seasons and divisions

The rules that #106, #107, #108 and #109 build on, so all four implement the same thing. The rules are also code: `teams/season_rules.py` and `teams/catalog_rules.py`. Import the helpers named below instead of writing your own checks. If a rule here needs to change, change this file and the helper in the same PR.

## Status

Proposed. Awaiting team sign-off on #105. Until then, treat it as the plan, not as settled.

## Sports and event types

- A `Sport` has many `EventType`s. Each `EventType` has a foreign key to one `Sport`.
- Sport names are unique ignoring case and extra whitespace: "Ultimate  Frisbee", " ultimate frisbee" and "Ultimate Frisbee" are the same sport. Event-type names are unique the same way, within their sport (two sports can each have a "Pickup" event type).
- Names are 1 to 50 characters after normalizing.
- Teams and free-agent requests choose a `Sport`, and it is required. They don't choose an event type in E2 (see Deferred).
- Only League Admins (`LEAGUE_ADMIN_ROLE` in `accounts/roles.py`) and superusers manage sports and event types.

Helpers in `teams/catalog_rules.py`:

| Helper | Use it to |
|---|---|
| `normalize_name` | Clean a name before saving it (strip, collapse whitespace) |
| `name_key` | Compare names for uniqueness and matching (normalized and casefolded) |
| `validate_catalog_name` | Validate a sport, event-type or division name in a form; returns the cleaned name or raises "Enter a name." / "Use 50 characters or fewer." |
| `MAX_NAME_LENGTH` | The 50-character limit (same as today's `sport` field) |
| `group_legacy_sports` | Group existing sport text into one `Sport` per name (data migration only) |

## Season lifecycle

A season is always in exactly one state (`SeasonState` in `teams/season_rules.py`):

| State | Label | Meaning |
|---|---|---|
| `draft` | Draft | Being set up. Players can't see it. |
| `open` | Open | Registration: teams can be created and players can ask to be placed. |
| `active` | Active | The season is under way. |
| `closed` | Closed | Finished. Read-only. |

Allowed transitions (`ALLOWED_TRANSITIONS`):

- draft → open
- open → draft (pull a season back for more setup)
- open → active
- active → closed

Nothing else. `closed` is final. Moving a season to the state it is already in is rejected, and so is any state name not in the table. Check with `can_transition`, or call `validate_transition`, which raises a `ValidationError` like "A season can't move from Closed to Open."

**Who:** only League Admins and superusers create or edit seasons and change their state.

## What each state allows

| Action (`SeasonAction`) | draft | open | active | closed |
|---|---|---|---|---|
| `create_team` | no | yes | no | no |
| `request_free_agent` | no | yes | yes | no |
| `match_free_agents` | no | yes | yes | no |
| `add_player` | no | yes | yes | no |
| `remove_player` | no | yes | no | no |
| `leave_team` | no | yes | no | no |

Rosters are locked once a season is `active`: players can still be added (by the captain or by free-agent matching), but nobody can leave or be removed, so no one switches teams mid-season. The existing one-team-per-season rule already stops a player joining a second team.

Ask with `season_allows(season.state, action)`. It returns `False` for an unknown state. Don't compare state strings in views or forms.

## Dates

- `start_date` is required.
- `end_date` is optional. When set, it can't be before `start_date`. A one-day season (`end_date == start_date`) is fine.

Check with `validate_season_dates(start_date, end_date)`. It raises a `ValidationError` on `end_date`: "The end date can't be before the start date."

## Divisions

- A season has zero or more divisions. Division names are unique within the season, with the same normalization as sports (`name_key`, `validate_catalog_name`).
- A team may have a division, and it must be a division of the team's own season. No division is fine.
- A free-agent request may name a division of its season. No division is fine.
- Matching: a request with no division can go to any team of its sport. A request with a division goes only to teams in that division. Use `division_matches(team_division_id, request_division_id)`.
- Only League Admins and superusers manage divisions.

## Migrating existing data

Today's fields and what they become:

| Today (`teams/models.py`) | After E2 | How |
|---|---|---|
| `Season.is_active = True` | `state = "open"` | `state_from_legacy_is_active(True)`. Today an active season allows team creation, requests and matching, which is exactly `open`. |
| `Season.is_active = False` | `state = "closed"` | `state_from_legacy_is_active(False)` |
| `Team.sport` (text, max 50) | `Team.sport` FK to `Sport` | Three migrations, below |
| `FreeAgentRequest.sport` (text, max 50) | `FreeAgentRequest.sport` FK to `Sport` | Same three migrations |

Sport text to `Sport` FK, in three migrations:

1. Add a nullable `Sport` FK next to the text field.
2. Backfill: run `group_legacy_sports` over every `Team.sport` and `FreeAgentRequest.sport` value, create one `Sport` per key (display name = most common spelling, ties go to the alphabetically first, so "Soccer" beats "soccer"), and point each row at the `Sport` for `name_key(row.sport)`. Blank values don't create a `Sport`.
3. Make the FK required and drop the text field.

The reverse of step 2 writes `sport.name` back into the text field.

Places that read the old fields and must change in the same PR as the migration:

- `Season.objects.filter(is_active=True)` in `FreeAgentRequestForm.__init__` (`teams/forms.py`), and the `is_active=True` lookups in `free_agent_pool`, `manage_free_agents`, `manage_season_free_agents` and `match_free_agents` (`teams/views.py`).
- `TeamCreateForm` (`teams/forms.py`): `sport` is a free-text model field today, and `season` lists every season.
- `FreeAgentRequestForm.sport` and `clean_sport` (`teams/forms.py`): a free-text `CharField` today.
- `match_free_agents` (`teams/views.py`): `team.sport.casefold() == free_agent.sport.casefold()` becomes FK equality (`team.sport_id == free_agent.sport_id`). Same result as today, except that names differing only in spacing now also match, because the backfill groups them.
- `TeamAdmin.list_display` (`teams/admin.py`) shows `sport`; it keeps working with an FK.

## How #106/#107/#108 use this

| Issue | Imports | Rule it must enforce |
|---|---|---|
| #106 Manage sports and event types | `validate_catalog_name`, `name_key`, `group_legacy_sports` | Sport names are unique by `name_key`; event-type names are unique by `name_key` within their sport; the sport text fields move to a required `Sport` FK in the three migrations above. |
| #107 Season lifecycle and League Admin controls | `SeasonState`, `can_transition` / `validate_transition`, `SeasonAction`, `season_allows`, `validate_season_dates`, `state_from_legacy_is_active` | Every `is_active` check becomes a `season_allows` check for the matching action, and `add_player`, `remove_player` and `leave_team` check `add_player` / `remove_player` / `leave_team`; state changes only along `ALLOWED_TRANSITIONS`, and only by League Admins or superusers. |
| #108 Optional season divisions | `validate_catalog_name`, `name_key`, `division_matches` | A team's division belongs to its own season; matching only places a request with a division on a team in that division. |
| #109 Admin workflow and integration tests | All of the above | Tests the whole flow end to end: create sport, create season, open it, register teams and requests, match, activate, close. |

## Deferred

- Event types on teams and free-agent requests. E2 creates event types but nothing chooses one yet.
- Division-aware free-agent requests are **in** scope (see Divisions), not deferred.

## Open questions for #105

Not yet decided. Answer these on #105 before #107 starts, then move the answers into the sections above.

- **Teams with no season.** `Team.season` is nullable today. Do lifecycle rules apply to such teams at all, or does E2 require every new team to have a season?
- **Cancelling a free-agent request.** Allowed wherever `request_free_agent` is (open and active), or only in `open`?
- **Draft visibility.** "Players can't see a draft season" has no helper yet. Is it enough for each list and form to exclude `draft`, or should there be a shared queryset helper?
