# Match detail page and stats Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give each match a page with the final score, period scores, appearances and player stats. League Admins and the assigned Scorekeeper enter that data on the existing score pages.

**Architecture:** Three new tables in `matches` (`MatchPeriodScore`, `PlayerStat`, `MatchAppearance`) and two new fields on `teams.Sport`. A single writer, `matches/stats.py:save_match_sheet`, copies the period totals into `Match.home_score`/`away_score`, so the standings code does not change. A `MatchSheet` form bundle replaces `ScoreForm` in the two score views. A new read-only view `match_detail` shows everything, and match rows link to it.

**Tech Stack:** Django, Django templates, Tabler (docs/DESIGN.md), the Django test runner, coverage.

**Spec:** `docs/superpowers/specs/2026-11-15-match-detail-stats-design.md`

## Global Constraints

- Branch: `nihal/match-detail-stats`, created from `origin/testing`. Do not commit to `main` or `testing`. Open the PR into `testing` only when your user asks.
- Commit messages have no Claude co-author line or footer.
- Do not create GitHub issues or ZenHub cards. The coordinator does that.
- Shared contract names are fixed: `Sport.period_count`, `Sport.period_label`, `MatchPeriodScore` (`related_name="period_scores"`), `PlayerStat` (`related_name="player_stats"`), `MatchAppearance` (`related_name="appearances"`, player `related_name="match_appearances"`).
- The name fallback is the text `PlayNYU player`. Match pages and the score form never render an email.
- Overtime: at most 2 extra periods, labelled `OT1`, `OT2`.
- A final score alone is valid for a sport with periods.
- Every template extends `base.html`, uses `components/` partials, and puts `pn-num` on every number. There is no `<style>` and no JavaScript.
- CI: `black --check .`, `flake8 .`, `coverage run manage.py test`, `coverage report --fail-under=80`.

## Review Focus

1. **Tampered POST.** A field such as `stat-<team>-<stranger>-<et>` or `played-...` for a player who is not on the sheet is ignored. It creates no row (Task 4).
2. **Oversized numbers.** `10000` in a period or stat input gives a form error, not a database error. All number inputs use `max_value=9999` (Task 4).
3. **Player who switched teams.** A player left the home team and joined the away team in the same season. They show under both teams, but `played` for both is refused: "{name} can only play for one team." (Task 3, Task 4)
4. **Scorekeeper who lost the role.** The assigned user no longer has the Scorekeeper role. The match page shows no button (Task 6).
5. **Event type added after scoring.** A new event type for the sport shows as a blank column on the form and as `0` on the page. Nothing errors (Task 6).

---

## File structure

| File | Change | Responsibility |
|---|---|---|
| `teams/models.py` | Modify | `Sport.period_count`, `period_label`, `period_name()`, lower-limit check in `clean` |
| `teams/migrations/0013_sport_periods.py` | Create | Adds the two fields |
| `teams/forms.py`, `teams/views.py`, `teams/urls.py` | Modify | `SportForm` fields, `edit_sport` view and URL |
| `teams/templates/teams/edit_sport.html`, `manage_sports.html` | Create / modify | Edit form, Edit link per sport row |
| `matches/models.py` | Modify | Three new models, `validate_match_player`, `Match.has_periods` |
| `matches/migrations/0004_match_stats.py` | Create | The three tables |
| `matches/stats.py` | Create | `team_sheets()` (read model) and `save_match_sheet()` (the only writer) |
| `matches/sheet_forms.py` | Create | `PeriodForm`, `BasePeriodFormSet`, `PlayerStatForm`, `MatchSheet` |
| `matches/forms.py` | Modify | `ScoreForm(required=...)` |
| `matches/views.py`, `matches/urls.py` | Modify | `match_detail`, score views use `MatchSheet` |
| `matches/templates/matches/match_detail.html` | Create | Match page |
| `matches/templates/matches/score_form.html` | Modify | Full-width match sheet |
| `core/templatetags/ui.py` | Modify | `player_name` filter |
| `templates/components/match_row.html`, `matches/templates/matches/_my_match_row.html` | Modify | Link to the match page |
| `docs/DESIGN.md` | Modify | "Match" and "Record the score" recipes, match-row link rule |
| `matches/test_match_models.py`, `test_match_sheet.py`, `test_match_detail.py`, `teams/test_sport_periods.py` | Create | Tests |

Test fixtures: subclass `matches.tests.MatchFixtures` (gives `admin`, `player`, `soccer`, `hoops`, `season`, `home` "Violets", `away` "Bobcats", `field`, `build()`) and `ScorekeeperFixtures` (`keeper`, `other_keeper`, `remove_role()`). Add roster rows with `Roster.objects.create(team=..., player=...)`.

---

### Task 1: Branch and sport period settings

**Files:**
- Modify: `teams/models.py` (`Sport`), `teams/forms.py` (`SportForm`), `teams/views.py`, `teams/urls.py`, `teams/templates/teams/manage_sports.html`
- Create: `teams/migrations/0013_sport_periods.py`, `teams/templates/teams/edit_sport.html`, `teams/test_sport_periods.py`

**Interfaces:**
- Produces: `Sport.period_count: int` (default 4, 0..10), `Sport.period_label: str` (default `"Q"`, max 10), `Sport.period_name(n: int) -> str`, URL `teams:edit_sport` (`sports/<int:pk>/edit/`).

- [ ] **Step 1: Create the branch**

Run: `git fetch origin && git checkout -b nihal/match-detail-stats origin/testing`
Expected: `Switched to a new branch 'nihal/match-detail-stats'`

- [ ] **Step 2: Write failing tests in `teams/test_sport_periods.py`**

```python
def test_defaults(self):            # Sport.objects.create(name="Rugby") -> period_count 4, period_label "Q"
def test_period_name(self):
    s = Sport(name="X", period_count=4, period_label="Q")
    assert [s.period_name(n) for n in (1, 4, 5, 6)] == ["Q1", "Q4", "OT1", "OT2"]
    s.period_label = "Half"; s.period_count = 2
    assert s.period_name(2) == "Half 2"
def test_period_count_max_10(self): # full_clean with 11 -> ValidationError on period_count
def test_zero_periods_allowed(self) # full_clean with 0 passes
def test_edit_sport_saves_periods(self):  # admin POST {"name": "Soccer", "period_count": 2, "period_label": "Half"} -> 302 to teams:manage_sports, values stored
def test_edit_sport_denies_casual_player(self):  # 403; anonymous 302
def test_manage_sports_links_edit(self):  # GET manage_sports contains reverse("teams:edit_sport", args=[sport.pk])
```

- [ ] **Step 3: Run the tests and make sure they fail**

Run: `python manage.py test teams.test_sport_periods -v 2`
Expected: FAIL (`AttributeError: period_name`, `NoReverseMatch: edit_sport`)

- [ ] **Step 4: Implement**

- Add the fields to `Sport`: `PositiveSmallIntegerField(default=4, validators=[MaxValueValidator(10)])` and `CharField(max_length=10, default="Q")`. `period_name(n)` returns `OT{n - period_count}` when `n > period_count`. Otherwise it returns `{label}{n}` when the label is 2 characters or fewer, and `{label} {n}` when it is longer.
- `python manage.py makemigrations teams --name sport_periods`. Make sure that the file is `0013_sport_periods.py`.
- `SportForm.Meta.fields = ["name", "period_count", "period_label"]`. Labels: "Periods per match", "Period label". Help text on `period_label`: "Q gives Q1, Q2. Half gives Half 1, Half 2."
- `edit_sport(request, pk)`: `_require_league_admin`, `SportForm(instance=sport)`, on success the message "Saved {sport}." and redirect to `teams:manage_sports`. `nav_section="league_setup"`. The template is a `pn-auth` card like `score_form.html`, with "Save sport" (primary) and "Cancel" (ghost).
- In `manage_sports.html`, add `<a class="btn btn-sm btn-outline-secondary ms-auto" href="{% url 'teams:edit_sport' sport.pk %}">Edit</a>` to each row. Add "· {{ sport.period_count }} periods" to the meta line.
- The add form now shows the period fields too. They are fine with their defaults.

- [ ] **Step 5: Run the tests and make sure they pass**

Run: `python manage.py test teams -v 1`
Expected: OK. The existing sport tests still pass with the defaults.

- [ ] **Step 6: Commit**

```bash
git add teams/
git commit -m "Add period count and label to sports, with an edit page"
```

---

### Task 2: Period, stat and appearance models

**Files:**
- Modify: `matches/models.py`, `teams/models.py` (`Sport.clean`)
- Create: `matches/migrations/0004_match_stats.py`, `matches/test_match_models.py`

**Interfaces:**
- Consumes: `Sport.period_count` (Task 1).
- Produces:
  - `MatchPeriodScore(match, period, home_points, away_points)`
  - `PlayerStat(match, player, team, event_type, value)`
  - `MatchAppearance(match, player, team)`
  - `validate_match_player(row) -> None` (raises `ValidationError`)
  - `Match.has_periods -> bool`

- [ ] **Step 1: Write failing tests in `matches/test_match_models.py`**

```python
def test_period_unique_per_match(self)        # second (match, 1) -> IntegrityError
def test_period_must_be_at_least_1(self)      # period=0 -> IntegrityError (CheckConstraint "period_score_period_positive")
def test_period_limit_is_count_plus_2(self)   # soccer.period_count=4: period 6 full_clean OK, period 7 -> ValidationError on "period"
def test_stat_needs_roster_player(self)       # PlayerStat for a user with no Roster on home -> ValidationError "That player isn't on this team."
def test_stat_team_must_be_in_match(self)     # team=hoops_team -> ValidationError "Choose a team in this match."
def test_stat_event_type_same_sport(self)     # EventType of hoops -> ValidationError "Choose an event type for this sport."
def test_stat_unique(self)                    # second (match, player, event_type) -> IntegrityError
def test_left_player_row_still_cleans(self)   # create stat, delete Roster row, change value, full_clean passes
def test_appearance_same_rules(self)          # non-roster player -> ValidationError; second (match, player) -> IntegrityError
def test_event_type_with_stats_is_protected(self)  # event_type.delete() -> ProtectedError
def test_has_periods(self)                    # False, then True after one MatchPeriodScore
def test_sport_cannot_drop_below_stored_periods(self):
    # store period 4 on a soccer match (period_count 4); set period_count=1 -> full_clean
    # raises ValidationError {"period_count": ["Matches already have scores for period 4."]}
    # period_count=2 passes (4 <= 2 + 2)
```

- [ ] **Step 2: Run the tests and make sure they fail**

Run: `python manage.py test matches.test_match_models -v 2`
Expected: FAIL with `ImportError` for `MatchPeriodScore`

- [ ] **Step 3: Implement in `matches/models.py`**

- Use the fields, `on_delete` values and `related_name` values from the spec "Data model" section exactly. Add `UniqueConstraint`s named `unique_period_per_match`, `unique_stat_per_player_event` and `unique_appearance_per_match`. Add `CheckConstraint(period__gte=1, name="period_score_period_positive")`. `MatchPeriodScore.Meta.ordering = ["period"]`.
- `MatchPeriodScore.clean`: `period <= match.home_team.sport.period_count + 2`. Error: "Matches have at most 2 overtime periods."
- `validate_match_player(row)` is a module function. `PlayerStat.clean` and `MatchAppearance.clean` call it.
  - `row.team_id` is in `{match.home_team_id, match.away_team_id}`. Error key `team`: "Choose a team in this match."
  - The roster check runs only when `row.pk` is None, or when the stored `player_id` or `team_id` is different. Error key `player`: "That player isn't on this team."
- `PlayerStat.clean` also checks `event_type.sport_id == match.home_team.sport_id`. Error key `event_type`: "Choose an event type for this sport."
- `Sport.clean` in `teams/models.py`: when `self.pk`, read the highest stored `period` with `apps.get_model("matches", "MatchPeriodScore").objects.filter(match__home_team__sport=self).aggregate(Max("period"))`. Raise the error from the test when it is greater than `period_count + 2`. Use `apps.get_model` to avoid a circular import.
- `python manage.py makemigrations matches --name match_stats`. Make sure that the file is `0004_match_stats.py`.
- Register the three models in `matches/admin.py` with a plain `admin.site.register`.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `python manage.py test matches.test_match_models teams.test_sport_periods -v 2`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add matches/ teams/models.py
git commit -m "Add period score, player stat and appearance models"
```

---

### Task 3: Read model and the single writer

**Files:**
- Create: `matches/stats.py`, add tests to `matches/test_match_sheet.py`
- Modify: `core/templatetags/ui.py`

**Interfaces:**
- Consumes: the Task 2 models, `Sport.period_name`.
- Produces:

```python
@dataclass
class SheetRow:
    player: User
    on_roster: bool          # False -> "Left team"
    played: bool             # has a MatchAppearance for this team
    stats: dict[int, int]    # event_type_id -> value; missing means 0

@dataclass
class TeamSheet:
    team: Team
    rows: list[SheetRow]     # roster first by name, then leavers by name

def match_event_types(match) -> list[EventType]      # sport's event types, ordered by name
def team_sheets(match) -> list[TeamSheet]            # [home, away]; a fixed number of queries
def period_rows(match) -> list[tuple[str, int, int]] # (label, home, away) from stored rows
def save_match_sheet(match, *, periods, final, stats, played, players) -> None
#   periods: list[tuple[int, int, int]]   (period, home, away), complete rows only
#   final:   tuple[int, int] | None       used only when periods is empty
#   stats:   dict[tuple[int, int, int], int]  (team_id, player_id, event_type_id) -> value
#   played:  set[tuple[int, int]]         (team_id, player_id)
#   players: set[tuple[int, int]]         the (team_id, player_id) pairs this sheet edits
```

`{{ user|player_name }}` in `core/templatetags/ui.py` returns `user.get_full_name()` or `"PlayNYU player"`.

- [ ] **Step 1: Write failing tests (class `SaveMatchSheetTests`, `TeamSheetsTests`, `PlayerNameTests`)**

```python
def test_periods_set_the_final_score(self)     # periods [(1,10,8),(2,5,7),(5,3,0)] on soccer (count 4), final=(99,99) -> home_score 18, away_score 15; 3 period rows
def test_final_alone_clears_periods(self)      # stored periods, then periods=[] final=(2,1) -> 0 period rows, score 2-1
def test_zero_stat_deletes_row(self)           # stored value 2, then stats {key: 0} -> no PlayerStat
def test_stat_implies_appearance(self)         # stats {key: 1}, played=set() -> MatchAppearance exists
def test_unchecked_played_deletes_appearance(self)  # played was stored, played=set(), no stats -> gone
def test_rows_outside_players_untouched(self)  # stored stat for a leaver not in `players` survives a save
def test_one_team_per_player(self)             # played has (home, p) and (away, p) -> ValidationError "{name} can only play for one team."; nothing written
def test_error_rolls_back(self)                # stats key with a non-roster player -> ValidationError; score and periods unchanged
def test_team_sheets_rows(self)                # roster player A, leaver B with a stat -> home rows [A on_roster, B not on_roster, stats {et: 2}]
def test_team_sheets_query_count_is_fixed(self)  # assertNumQueries(n) with 2 players equals n with 4 players
def test_player_name_fallback(self)            # user with no names -> "PlayNYU player"; never the email
```

- [ ] **Step 2: Run the tests and make sure they fail**

Run: `python manage.py test matches.test_match_sheet -v 2`
Expected: FAIL with `ModuleNotFoundError: matches.stats`

- [ ] **Step 3: Implement `matches/stats.py` and the filter**

- `save_match_sheet` runs inside `transaction.atomic()`. First it calls `Match.objects.select_for_update().get(pk=match.pk)`.
- Delete and recreate the period rows, then set the scores from the sums (or from `final`). Save with `update_fields=["home_score", "away_score"]`.
- For each key in `stats`: when the value is 0, delete the row. Otherwise `update_or_create`. Call `full_clean(validate_unique=False)` on a new row before saving.
- The appearances to keep are `played` plus every `(team, player)` with a stat above 0, limited to `players`. Delete the appearances in `players` that are not kept, and create the missing ones with `full_clean` first.
- Check the one-team rule before any write.
- `team_sheets` uses one query each for the rosters, the stats and the appearances, then groups the results in Python.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `python manage.py test matches.test_match_sheet -v 2`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add matches/stats.py matches/test_match_sheet.py core/templatetags/ui.py
git commit -m "Add the match sheet read model and writer"
```

---

### Task 4: Match sheet forms

**Files:**
- Create: `matches/sheet_forms.py`
- Modify: `matches/forms.py` (`ScoreForm`), add tests to `matches/test_match_sheet.py`

**Interfaces:**
- Consumes: `team_sheets`, `match_event_types`, `save_match_sheet` (Task 3), and `ScoreForm`.
- Produces:
  - `ScoreForm(*args, required=True, **kwargs)`. Today's behavior stays the default.
  - `MatchSheet(match, data=None)`, with:
    - `.score_form`
    - `.periods`, a `BasePeriodFormSet`. Each form has `.label`, such as "Q1" or "OT1", and `.is_overtime`.
    - `.stats`, a `PlayerStatForm`. Its `.grid` is `list[tuple[TeamSheet, list[tuple[SheetRow, BoundField | None, list[BoundField | None]]]]]`. A leaver's slots are `None`.
    - `.non_field_errors()`, `.is_valid()` and `.save()`.

- [ ] **Step 1: Write failing tests (class `MatchSheetFormTests`)**

```python
def test_period_forms_count(self)            # soccer count 4 -> 6 forms, labels ["Q1".."Q4","OT1","OT2"]; period_count 0 -> no forms
def test_partial_regular_periods_fail(self)  # only Q1 filled -> error "Enter every period, or leave them all blank."
def test_overtime_needs_both_points(self)    # OT1 home only -> "Enter both teams' points."
def test_ot2_needs_ot1(self)                 # -> "Enter OT1 before OT2."
def test_overtime_needs_regular(self)        # OT1 only -> "Enter the regular periods before overtime."
def test_final_alone_valid(self)             # periods blank, final 2-1 -> valid
def test_nothing_entered_fails(self)         # -> "Enter both scores, or every period."
def test_periods_override_final(self)        # periods sum 18-15, final 1-0 -> save() -> 18-15
def test_number_limit(self)                  # stat or period 10000 -> form error, is_valid False (Review Focus 2)
def test_unknown_fields_ignored(self)        # POST stat-<away>-<stranger>-<et>=3 and played-... -> no PlayerStat or MatchAppearance (Review Focus 1)
def test_leaver_has_no_inputs(self)          # leaver row in grid has played field None and stat fields None
def test_switched_player_cannot_play_twice(self)  # played on both teams -> non-field error "{name} can only play for one team." (Review Focus 3)
def test_closed_season(self)                 # -> "Scores can only be recorded while the season is open or active."
```

- [ ] **Step 2: Run the tests and make sure they fail**

Run: `python manage.py test matches.test_match_sheet.MatchSheetFormTests -v 2`
Expected: FAIL with `ModuleNotFoundError: matches.sheet_forms`

- [ ] **Step 3: Implement**

- `ScoreForm`: with `required=False`, leave both fields optional. Add the help text "When you enter periods, the final score is their total." The both-or-neither and season checks stay.
- `PeriodForm`: `home_points` and `away_points` are `IntegerField(required=False, min_value=0, max_value=9999)`. Build the formset with `formset_factory(PeriodForm, formset=BasePeriodFormSet, extra=0)` and `prefix="period"`. Give it `period_count + 2` initial dicts from the stored rows. `BasePeriodFormSet.filled() -> list[tuple[int, int, int]]`.
- `PlayerStatForm`: build the fields from `team_sheets(match)` and `match_event_types(match)`, for on-roster rows only. Stat fields are named `stat-<team>-<player>-<et>` (`IntegerField(required=False, min_value=0, max_value=9999)`). Played fields are named `played-<team>-<player>` (`BooleanField(required=False)`). For widget attrs, the stat `aria-label` is "{player_name}, {event type}" and the played `aria-label` is "{player_name} played".
- `MatchSheet.save()` turns the cleaned data into the `save_match_sheet` arguments. `players` is every on-roster `(team, player)` pair. A `ValidationError` from the writer becomes a non-field error, so `is_valid()` must call the one-team check first.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `python manage.py test matches -v 1`
Expected: OK. `test_results.ScoreFormTests` still passes.

- [ ] **Step 5: Commit**

```bash
git add matches/sheet_forms.py matches/forms.py matches/test_match_sheet.py
git commit -m "Add the match sheet forms for periods, stats and appearances"
```

---

### Task 5: Score views use the match sheet

**Files:**
- Modify: `matches/views.py` (`_score_match`, `record_score`, `submit_score`), `matches/templates/matches/score_form.html`, `matches/test_results.py`, `matches/test_scorekeeping.py`
- Test: `matches/test_match_sheet.py` (class `ScoreViewTests`)

**Interfaces:**
- Consumes: `MatchSheet` (Task 4), URL `matches:detail` (Task 6). Add the URL line in this task: `path("<int:pk>/", views.match_detail, name="detail")`. Add a stub `match_detail` that returns `render(request, "matches/match_detail.html", {"match": match})`, and a stub `match_detail.html` that extends `base.html` with `<h1>{{ match }}</h1>`, so `assertRedirects` can fetch it. Task 6 fills both in.
- Produces: `_score_match(request, match, nav_section) -> HttpResponse`

- [ ] **Step 1: Write failing tests**

```python
def test_admin_saves_sheet_and_goes_to_detail(self)   # POST periods + stats -> assertRedirects to matches:detail; PlayerStat stored
def test_keeper_saves_sheet(self)                     # assigned keeper, started match -> redirect to matches:detail
def test_other_keeper_403(self)
def test_cancelled_and_closed_redirect_as_today(self) # admin -> matches:manage?season=..., keeper -> matches:mine, same messages
def test_form_shows_grid(self)                        # GET contains 'name="played-<home>-<p>"', "OT1", aria-label "Alex Lee, Goal"
def test_no_email_on_form(self)                       # rostered user with no name -> "PlayNYU player", email not in content
def test_no_stat_section_without_event_types(self)    # hoops sport, no event types -> no "stat-" inputs; played checkboxes still render
```

- [ ] **Step 2: Run the tests and make sure they fail**

Run: `python manage.py test matches.test_match_sheet.ScoreViewTests -v 2`
Expected: FAIL (redirect goes to the list, no `played-` input)

- [ ] **Step 3: Implement**

- `_score_match` builds `MatchSheet(match, request.POST or None)`. On a valid POST, it saves, adds the message "Saved the score for {match}.", and redirects to `reverse("matches:detail", args=[match.pk])`. The template's Cancel link goes to the same URL. Keep every check in `record_score` and `submit_score` before this call.
- `score_form.html`: page header and the overwrite alert as today. Then `row row-cards` with `col-lg-4` (the "Final score" card through `form_fields.html`, then the "Periods" card) and `col-lg-8` (one card per team). Use the layout from the spec "Templates" section. Each table goes in `table-responsive`, and each input goes through the `control` filter with `form-control-sm pn-num text-end`. A leaver row shows the stored values as text with `badge bg-secondary-lt` "Left team". Put "Save score" (primary) and "Cancel" (ghost) below the row.
- Update the redirect assertions in `matches/test_results.py` (lines 107, 124, 134, 164, 184) and `matches/test_scorekeeping.py`. Change them only where they test a successful save; the refusal redirects stay.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `python manage.py test matches -v 1`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add matches/
git commit -m "Enter periods, appearances and player stats on the score page"
```

---

### Task 6: Match detail page

**Files:**
- Modify: `matches/views.py` (`match_detail`)
- Create: `matches/templates/matches/match_detail.html`, `matches/test_match_detail.py`

**Interfaces:**
- Consumes: `team_sheets`, `match_event_types`, `period_rows` (Task 3), `seasons_visible_to`, `has_role`.
- Produces: the context `match`, `sheets`, `event_types`, `periods`, `score_url` (str or None) and `nav_section="schedule"`.

- [ ] **Step 1: Write failing tests**

```python
def test_anonymous_redirects_to_login(self)
def test_player_sees_page(self)                 # 200; team names link to teams:detail; facility link only when active
def test_draft_season_hidden(self)              # player 404, admin 200
def test_period_table(self)                     # stored Q1..Q4 + OT1 -> headers "Q1".."Q4","OT1","T"; no "OT2"
def test_no_period_table_without_periods(self)  # final-only match -> no "Q1"
def test_did_not_play(self)                     # scored match, rostered player with no appearance -> "Did not play"
def test_left_team_row(self)                    # leaver with stat -> "Left team" and the value
def test_no_email(self)                         # unnamed player -> "PlayNYU player"; email absent from content
def test_new_event_type_shows_zero(self)        # event type added after scoring -> column header present, row shows 0 (Review Focus 5)
def test_before_result(self)                    # -> "Stats appear after the score is in."
def test_cancelled(self)                        # -> "Cancelled" badge; no score; no stat columns; rosters listed
def test_button_admin(self)                     # score_url == reverse("matches:score", args=[pk]) when can_change
def test_button_keeper(self)                    # assigned keeper, started -> matches:submit_score; before start -> None
def test_button_hidden_after_role_loss(self)    # remove_role(keeper) -> None (Review Focus 4)
def test_button_hidden_closed_season(self)      # closed season -> None for admin
def test_query_count_fixed(self)                # assertNumQueries equal for 2 and 4 players with stats
```

- [ ] **Step 2: Run the tests and make sure they fail**

Run: `python manage.py test matches.test_match_detail -v 2`
Expected: FAIL (the stub page has no period table, rosters or button)

- [ ] **Step 3: Implement**

- `match_detail` is `@login_required` and uses `get_object_or_404(Match.objects.filter(season__in=seasons_visible_to(request.user)).select_related("season", "facility", "home_team__sport", "away_team__sport", "home_team__division"), pk=pk)`.
- `score_url`:
  - For a League Admin or superuser, when `match.can_change`: `matches:score`.
  - For the assigned scorekeeper who still has `SCOREKEEPER_ROLE`, when `match.can_submit_score`: `matches:submit_score`.
  - Otherwise `None`.
- The template follows the spec "Templates" sketch:
  - The page header has the season (and division, if any) as the `subheader`, then `{{ home }} vs {{ away }}`, a meta line with time and facility, and the `btn-primary` "Record score" when `score_url` is set.
  - The scoreboard card shows `team_logo` `xl`, team names linked to `teams:detail`, and `h1 mb-0 pn-num` with the score. Badges: Final (`bg-green-lt`), Scheduled, Awaiting score (`bg-yellow-lt`, after the end with no result) and Cancelled (`bg-secondary-lt`).
  - The periods card is a `card-table`.
  - Each team gets one card in `col-lg-6`, with `avatar` `sm`, `{{ row.player|player_name }}` linked by `profile_url` when active, `pn-row-me` for the viewer, and an empty state "No players on this roster."

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `python manage.py test matches -v 1`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add matches/
git commit -m "Add the match detail page"
```

---

### Task 7: Link match rows and document the design

**Files:**
- Modify: `templates/components/match_row.html`, `matches/templates/matches/_my_match_row.html`, `docs/DESIGN.md`
- Test: `matches/test_match_detail.py` (class `MatchRowLinkTests`)

- [ ] **Step 1: Write failing tests**

```python
def test_season_schedule_links_match(self)   # GET matches:season_schedule contains href to matches:detail
def test_team_page_links_match(self)         # GET teams:detail for home contains the same href
def test_my_matches_links_match(self)        # keeper GET matches:mine contains the href
```

- [ ] **Step 2: Run the tests and make sure they fail**

Run: `python manage.py test matches.test_match_detail.MatchRowLinkTests -v 2`
Expected: FAIL

- [ ] **Step 3: Implement**

- In both row partials, wrap the "Home vs Away" `div` contents in `<a class="text-reset" href="{% url 'matches:detail' match.pk %}">`. Do not use `stretched-link`. The facility link and the action button stay as they are.
- `docs/DESIGN.md`:
  - In "Match rows", add one line saying the matchup links to `matches:detail`.
  - In section 6, add a "Match" recipe row and a "Record the score" recipe row, copied from the spec's template sketches.
  - In section 9, add `player_name` to the filter list.

- [ ] **Step 4: Run the tests and make sure they pass, then check the pages by eye**

Run: `python manage.py test matches teams -v 1`
Expected: OK. Then `python manage.py runserver`, and open a match page and the score form at 375px and 1280px. There must be no sideways page scroll. Take before/after screenshots for the PR.

- [ ] **Step 5: Commit**

```bash
git add templates/components/match_row.html matches/templates/matches/_my_match_row.html docs/DESIGN.md matches/test_match_detail.py
git commit -m "Link match rows to the match page and document the recipes"
```

---

### Task 8: Run the CI checks

- [ ] **Step 1: Format**

Run: `black .` and then `black --check .`
Expected: `All done!` with no files to reformat

- [ ] **Step 2: Lint**

Run: `flake8 .`
Expected: no output

- [ ] **Step 3: Test with coverage**

Run: `coverage run manage.py test`
Expected: `OK`

- [ ] **Step 4: Coverage floor**

Run: `coverage report --fail-under=80`
Expected: exit code 0. Check that `matches/stats.py` and `matches/sheet_forms.py` are each at 90% or more.

- [ ] **Step 5: Commit any formatting fixes**

```bash
git add -A
git commit -m "Format match stats work"
```

Skip this commit when `git status` is clean. Push and open the PR into `testing` only when your user asks.
