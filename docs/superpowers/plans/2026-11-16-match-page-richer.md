# Richer match page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add top performers, team context, box score totals with a comparison, venue and officials, and standings movement to the match page (#255), at a fixed query count.

**Architecture:** Two new season-wide queries (`season_teams`, `season_results`) feed pure functions in a new `matches/match_context.py` (team context, head-to-head, standings before/after via `rank_rows`). Top performers, totals and the comparison are pure functions in `matches/stats.py` over the `team_sheets()` data the page already loads. The venue map reuses the facilities Leaflet partials through a public `facilities/maps.py:map_marker`. No models and no migrations.

**Tech Stack:** Django, Django templates, Tabler (docs/DESIGN.md), Leaflet 1.9.4 partials, the Django test runner, coverage.

**Spec:** `docs/superpowers/specs/2026-11-16-match-page-richer-design.md`

## Global Constraints

- Start only after PR #254 (`nihal/scoring-event-types`) merges into `testing`. Branch: `git fetch origin && git checkout -b nihal/match-page-richer origin/testing`. Do not commit to `main` or `testing`.
- Commit messages have no Claude co-author line or footer.
- No GitHub issue, ZenHub or PR steps in this plan. The coordinator does those.
- No new models, fields or migrations. `makemigrations --check` must stay clean.
- The page never renders an email. Names use `display_name` (Python: `core.names.display_name`). The fallback is `PlayNYU player`.
- Order key of a match: `(starts_at, pk)`. "Before" = counted season matches with a smaller key. "After" = before plus this match.
- Table choice: the team's division table when it has a division, else the season table. Each team chooses on its own.
- Standings movement, top performers, totals and the comparison show only for a counted match (`has_result and not is_cancelled`).
- Team context shows the season today, labelled "Season so far", or "Final standings" for a closed season.
- Top performers: at most 3 stats per team, scoring stat first. Section order: scoreboard, standings movement, top performers, box score, team context, venue (spec "Decisions").
- No JavaScript and no Chart.js. Bars are Tabler `progress` with inline `width` on `.progress-bar` only.
- Query budget: baseline `B` + 2 (B = 14, so at most 16), the same for 2 and 20 roster players and for 1 and 30 other season matches.
- Every template extends `base.html`, uses `components/` partials, and puts `pn-num` on every number.
- CI: `black --check .`, `flake8 .`, `coverage run manage.py test`, `coverage report --fail-under=80`, `python manage.py makemigrations --check --dry-run`.

## Review Focus

1. **Same start time.** Two matches in the season start at the same minute on different courts. The one with the lower pk is "before" the other; neither is before itself (Task 3).
2. **Score corrected later.** A League Admin changes this match's score from a win to a loss. The movement card flips on the next load with no stale data (Task 6).
3. **First match of the season.** Every team has 0 played before. Both teams show "First result", never an arrow made from the alphabetical tie-break (Task 3).
4. **Nameless people.** A top performer and the scorekeeper have no first or last name. The page shows "PlayNYU player" and no email (Task 7).
5. **Inactive venue.** The facility is inactive but has coordinates. No map (the marker popup would link to a 404) and no venue link; the address still shows (Task 5, Task 7).

## Change after approval (2026-11-16)

Standings movement renders as the full standings table after the match (spec Decisions, 6). `matches/match_context.py` gains `table_division`, `TableRow`, `StandingsTable` and `standings_table(match, teams, results)`; `standings_movement` returns `standings_table(...).movements`. The table is the shared division, else the season table. The view passes `standings_table`. `_movement.html` renders the leaderboard with `pn-row-match` rows and ▲/▼/–/New markers with `aria-label`s. Tests: full table, both teams tinted, each marker's text, colour class and label, the division table, and the unchanged query count.

---

## File structure

| File | Change | Responsibility |
|---|---|---|
| `matches/standings.py` | Modify | Extract `positions(rows)` from `standings_by_team` |
| `matches/match_context.py` | Create | `Result`, `season_results`, `season_teams`, `team_context`, `head_to_head`, `standings_movement` |
| `matches/stats.py` | Modify | `ordered_event_types`, `top_performers`, `team_totals`, `comparison_rows` |
| `facilities/maps.py` | Create | Public `map_marker(facility)` |
| `facilities/views.py` | Modify | Import `map_marker`; drop `_map_marker` |
| `matches/views.py` | Modify | `match_detail` builds the new context |
| `matches/templates/matches/match_detail.html` | Modify | Layout: scoreboard, `col-lg-8` main, `col-lg-4` rail, box scores |
| `matches/templates/matches/detail/_top_performers.html` | Create | Section 1 |
| `matches/templates/matches/detail/_movement.html` | Create | Section 5 |
| `matches/templates/matches/detail/_comparison.html` | Create | Section 3, bars |
| `matches/templates/matches/detail/_box_score.html` | Create | Team tables, moved from the page, plus `<tfoot>` totals |
| `matches/templates/matches/detail/_team_context.html` | Create | Section 2 |
| `matches/templates/matches/detail/_venue.html` | Create | Section 4 |
| `static/css/playnyu.css` | Modify | `--pn-series-2`, `.pn-bar-away`, `.pn-form-chip` under "Match page" |
| `docs/DESIGN.md` | Modify | Match recipe, Form chips, Comparison bars, Movement, Where things live |
| `matches/test_match_context.py` | Create | Pure-function tests (Tasks 1–4) |
| `matches/test_match_detail.py` | Modify | View, template and query tests (Tasks 6–7) |
| `facilities/tests.py` | Modify | `map_marker` test (Task 5) |

---

### Task 0: Branch and baseline

**Files:** none changed.

- [ ] **Step 1: Confirm #254 merged**

Run: `gh pr view 254 --json state -q .state`
Expected: `MERGED`. If not, stop and tell your user.

- [ ] **Step 2: Create the branch**

Run: `git fetch origin && git checkout -b nihal/match-page-richer origin/testing`

- [ ] **Step 3: Read #254's helper**

Run: `git grep -n "def scoring_event_type\|is_scoring" -- '*.py'`
Write down its module and signature. This plan assumes `scoring_event_type(sport) -> EventType | None` with 1 query. If it also accepts a loaded list, use that form in Task 6 and set the budget to `B + 2`.

- [ ] **Step 4: Measure the baseline `B`**

Temporarily add `print("BASELINE", expected)` after `expected = len(captured)` in `matches/test_match_detail.py::MatchDetailTests.test_query_count_fixed`.
Run: `python manage.py test matches.test_match_detail.MatchDetailTests.test_query_count_fixed`
Write down the number. Revert the print (`git checkout matches/test_match_detail.py`). Expected: `git status` is clean.

---

### Task 1: Extract `positions(rows)`

**Files:**
- Modify: `matches/standings.py` (`standings_by_team`)
- Test: `matches/test_match_context.py` (create)

**Interfaces:**
- Produces: `positions(rows: list[dict]) -> dict[int, dict]`. Input is `rank_rows()` output. Each value: `{"row", "position", "of", "division_position", "division_of"}`, the same keys as a `standings_by_team` entry. `of` is `len(rows)`. Division values are `None` for a team with `division_id is None`.

- [ ] **Step 1: Write the failing tests**

In `matches/test_match_context.py`, a `SimpleTestCase` with helper `team(pk, name, division=None)` returning `SimpleNamespace(pk=pk, name=name, division_id=division.pk if division else None, division=division)`. Task 2 adds a `result(...)` helper for `Result` tuples.

```python
def test_positions_season_and_division(self):
    east = SimpleNamespace(pk=1, name="East")
    a, b, c = team(1, "A", east), team(2, "B"), team(3, "C", east)
    rows = rank_rows([a, b, c], [(3, 2, 2, 0), (3, 1, 1, 0)])  # C beats B and A
    got = positions(rows)
    # C 6 pts; A and B 0 pts, split by name.
    self.assertEqual([got[t.pk]["position"] for t in (c, a, b)], [1, 2, 3])
    self.assertEqual(got[1]["of"], 3)
    self.assertEqual((got[3]["division_position"], got[3]["division_of"]), (1, 2))
    self.assertEqual((got[1]["division_position"], got[1]["division_of"]), (2, 2))
    self.assertIsNone(got[2]["division_position"])
    self.assertIsNone(got[2]["division_of"])
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python manage.py test matches.test_match_context`
Expected: FAIL, `ImportError: cannot import name 'positions'`.

- [ ] **Step 3: Implement `positions(rows)` in `matches/standings.py`**

Move the per-season loop body of `standings_by_team` into it. `standings_by_team` calls `positions(rank_rows(...))` per season and merges the dicts. Its docstring and 2-query behaviour stay.

- [ ] **Step 4: Run the new test and the standings tests**

Run: `python manage.py test matches.test_match_context matches.test_standings teams core`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add matches/standings.py matches/test_match_context.py
git commit -m "#255: Extract standings positions from standings_by_team"
```

---

### Task 2: Season data and team context

**Files:**
- Create: `matches/match_context.py`
- Test: `matches/test_match_context.py`

**Interfaces:**
- Consumes: `positions` (Task 1), `rank_rows`, `counted_matches` (`matches/standings.py`).
- Produces:
  - `class Result(NamedTuple)`: `pk, starts_at, home_id, away_id, home_score, away_score`.
  - `season_results(match) -> list[Result]`: 1 query, `counted_matches().filter(season_id=match.season_id).order_by("starts_at", "pk").values_list(...)`.
  - `season_teams(match) -> list[Team]`: 1 query, `select_related("division")`, ordered by name.
  - `@dataclass Form`: `match_pk, letter, scored, conceded, opponent, starts_at, is_this_match`. `letter` is `"W"`, `"D"` or `"L"`.
  - `@dataclass TeamContext`: `team, row, standing, form`. `row` is the `rank_rows` dict, `standing` the `positions` entry, `form` a `list[Form]`.
  - `team_context(match, teams, results, limit=5) -> list[TeamContext]`: home, then away.
  - `@dataclass HeadToHead`: `home_wins, draws, away_wins, meetings` (`meetings`: `list[Result]`, newest first).
  - `head_to_head(match, results) -> HeadToHead`. `home_wins` counts wins of `match.home_team`, whichever side it played.

- [ ] **Step 1: Write the failing tests**

Use `SimpleNamespace` matches: `pk, starts_at, home_team_id, away_team_id, home_team, away_team, has_result, is_cancelled`. Use `datetime` values in UTC.

```python
def test_form_newest_first_capped_and_marks_this_match(self):
    # Seven results for team A; this match is the 4th.
    ctx = team_context(this, teams, results)
    self.assertEqual(len(ctx[0].form), 5)
    self.assertEqual([f.match_pk for f in ctx[0].form], [7, 6, 5, 4, 3])
    self.assertTrue(ctx[0].form[3].is_this_match)
    self.assertEqual(ctx[0].form[0].opponent, b)

def test_form_letters_from_each_side(self):
    # A 2-1 B: A gets W, B gets L. A 0-0 B: both D.

def test_record_and_position(self):
    self.assertEqual((ctx[0].row["won"], ctx[0].row["points"]), (2, 6))
    self.assertEqual(ctx[0].standing["position"], 1)

def test_no_results_gives_zero_played(self):
    ctx = team_context(this, teams, [])
    self.assertEqual(ctx[0].row["played"], 0)
    self.assertEqual(ctx[0].form, [])

def test_head_to_head_counts_both_orientations(self):
    # A 2-1 B (A home), B 1-1 A, B 3-0 A, A 1-0 C (skipped)
    h2h = head_to_head(this, results)
    self.assertEqual((h2h.home_wins, h2h.draws, h2h.away_wins), (1, 1, 1))
    self.assertEqual(len(h2h.meetings), 3)

def test_head_to_head_empty(self):
    self.assertEqual(head_to_head(this, []).meetings, [])
```

In `matches/test_match_detail.py` (DB), `SeasonQueryTests(SheetFixtures)`:

```python
def test_season_results_skip_cancelled_unscored_and_other_seasons(self):
    # one scored, one cancelled, one unscored, one scored in other_season
    self.assertEqual([r.pk for r in season_results(self.match)], [scored.pk])

def test_season_results_ordered_by_start_then_pk(self): ...
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python manage.py test matches.test_match_context matches.test_match_detail.SeasonQueryTests`
Expected: FAIL, `ModuleNotFoundError: matches.match_context`.

- [ ] **Step 3: Implement the functions in `matches/match_context.py`**

`team_context` calls `rank_rows(teams, [(r.home_id, r.away_id, r.home_score, r.away_score) for r in results])` once and `positions` once. Form walks `reversed(results)`. Skip a result whose opponent is not in `teams`.

- [ ] **Step 4: Run the tests**

Run: `python manage.py test matches.test_match_context matches.test_match_detail.SeasonQueryTests`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add matches/match_context.py matches/test_match_context.py matches/test_match_detail.py
git commit -m "#255: Season results, team context and head-to-head"
```

---

### Task 3: Standings movement

**Files:**
- Modify: `matches/match_context.py`
- Test: `matches/test_match_context.py`

**Interfaces:**
- Consumes: `Result`, `positions`, `rank_rows`.
- Produces:
  - `@dataclass Movement`: `team, table_label, before_position, after_position, of, before_points, after_points, direction, change`. `direction` in `{"up", "down", "same", "first"}`. `before_position` is `None` for `"first"`. `change` is `before_position - after_position`, 0 for `"first"`. `table_label` is the division name, or `None` for the season table.
  - `standings_movement(match, teams, results) -> list[Movement] | None`: `None` when `not match.has_result or match.is_cancelled`; else home, then away.

- [ ] **Step 1: Write the failing tests**

```python
def test_win_moves_up(self):
    # Before: A 5th, after this win: A 3rd (season table, no divisions)
    home = standings_movement(this, teams, results)[0]
    self.assertEqual((home.direction, home.change), ("up", 2))
    self.assertEqual((home.before_position, home.after_position), (5, 3))
    self.assertEqual(home.after_points - home.before_points, 3)

def test_loss_moves_down(self): ...  # direction "down", change < 0
def test_draw_same_position(self): ...  # direction "same", change 0, points +1

def test_same_start_lower_pk_is_before(self):
    # other match: same starts_at, pk = this.pk - 1 -> counted in before
def test_same_start_higher_pk_is_not_before(self):
    # other match: same starts_at, pk = this.pk + 1 -> in neither before nor after

def test_later_matches_ignored(self):
    # adding a later result leaves both Movement lists equal

def test_first_result(self):
    m = standings_movement(first_match, teams, results)
    self.assertEqual([x.direction for x in m], ["first", "first"])
    self.assertIsNone(m[0].before_position)

def test_division_table_for_division_team(self):
    # home in East (3 teams), away has no division (season of 5)
    m = standings_movement(this, teams, results)
    self.assertEqual((m[0].table_label, m[0].of), ("East", 3))
    self.assertEqual((m[1].table_label, m[1].of), (None, 5))

def test_cross_division_each_own_table(self): ...  # East vs West labels

def test_none_without_result_or_cancelled(self):
    self.assertIsNone(standings_movement(unscored, teams, results))
    self.assertIsNone(standings_movement(cancelled, teams, results))
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python manage.py test matches.test_match_context`
Expected: FAIL, `ImportError: cannot import name 'standings_movement'`.

- [ ] **Step 3: Implement `standings_movement` in `matches/match_context.py`**

Follow the spec's "Standings movement algorithm" steps 1–7. `key = (match.starts_at, match.pk)`; before uses `<`, after uses `<=`. `"first"` when `before_row["played"] == 0`.

- [ ] **Step 4: Run the tests**

Run: `python manage.py test matches.test_match_context`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add matches/match_context.py matches/test_match_context.py
git commit -m "#255: Standings before and after a match"
```

---

### Task 4: Top performers, totals and comparison

**Files:**
- Modify: `matches/stats.py`
- Test: `matches/test_match_context.py`

**Interfaces:**
- Consumes: `SheetRow`, `TeamSheet`, `_name_key` (`matches/stats.py`).
- Produces:
  - `ordered_event_types(event_types, scoring) -> list`: `scoring` first when it is in the list, then the rest in input order.
  - `@dataclass Leader`: `player, value, event_type`. Property `short_name`: `player.last_name.strip()` or `display_name(player)`.
  - `@dataclass TeamLeaders`: `team, leaders` (`list[Leader]`).
  - `top_performers(sheets, event_types, scoring) -> list[TeamLeaders]`: one per sheet, in sheet order. A team with no leader has `leaders == []`.
  - `team_totals(sheet, event_types) -> list[int]`: aligned to `event_types`.
  - `@dataclass ComparisonRow`: `event_type, home, away, home_pct`. Property `away_pct = 100 - home_pct`.
  - `comparison_rows(event_types, home_totals, away_totals, scoring) -> list[ComparisonRow]`: order from `ordered_event_types`; rows with `home == away == 0` left out; `home_pct = round(100 * home / (home + away))`.

- [ ] **Step 1: Write the failing tests**

Build `TeamSheet`s from `SheetRow`s with `SimpleNamespace` players (`pk, first_name, last_name, get_full_name`) and event types (`pk, name`).

```python
def test_scoring_type_first(self):
    self.assertEqual([l.event_type for l in tp[0].leaders], [points, assist, rebound])

def test_tie_goes_by_name_and_named_first(self):
    # Kim 5, Lee 5, nameless 5 -> Kim
def test_zero_never_leads(self):  # no stats for Rebound -> no Rebound leader
def test_player_who_left_can_lead(self):  # SheetRow(on_roster=False) with 30
def test_no_scoring_type_orders_by_name(self):  # scoring=None
def test_short_name(self):
    self.assertEqual(Leader(lee, 24, points).short_name, "Lee")
    self.assertEqual(Leader(nameless, 1, points).short_name, "PlayNYU player")

def test_totals_include_leavers(self):
    self.assertEqual(team_totals(sheet, [goal, assist]), [3, 1])

def test_comparison_skips_zero_rows_and_rounds(self):
    rows = comparison_rows([assist, goal], [1, 0], [2, 0], goal)
    self.assertEqual([r.event_type for r in rows], [assist])
    self.assertEqual((rows[0].home_pct, rows[0].away_pct), (33, 67))
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python manage.py test matches.test_match_context`
Expected: FAIL, `ImportError: cannot import name 'top_performers'`.

- [ ] **Step 3: Implement the functions in `matches/stats.py`**

Leader choice per (sheet, event type): `min` over rows with value > 0 by `(-value, *_name_key(row.player))`.

- [ ] **Step 4: Run the tests**

Run: `python manage.py test matches.test_match_context matches.test_stats`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add matches/stats.py matches/test_match_context.py
git commit -m "#255: Top performers, team totals and comparison rows"
```

---

### Task 5: Public `map_marker`

**Files:**
- Create: `facilities/maps.py`
- Modify: `facilities/views.py`
- Test: `facilities/tests.py`

**Interfaces:**
- Produces: `map_marker(facility) -> dict` with keys `name, lat, lng, url` (same values as `_map_marker` today). `facilities/views.py` no longer defines `_map_marker`.

- [ ] **Step 1: Write the failing test**

```python
def test_map_marker(self):
    facility = Facility.objects.create(
        name="Pier 40", source=Facility.Source.NYU,
        latitude=Decimal("40.7290"), longitude=Decimal("-74.0110"),
    )
    self.assertEqual(map_marker(facility), {
        "name": "Pier 40", "lat": 40.729, "lng": -74.011,
        "url": reverse("facilities:detail", args=[facility.pk]),
    })
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python manage.py test facilities.tests`
Expected: FAIL, `ModuleNotFoundError: facilities.maps`.

- [ ] **Step 3: Move the function to `facilities/maps.py` and import it in `facilities/views.py`**

- [ ] **Step 4: Run the facilities tests**

Run: `python manage.py test facilities`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add facilities/maps.py facilities/views.py facilities/tests.py
git commit -m "#255: Make the facility map marker public"
```

---

### Task 6: View context and query budget

**Files:**
- Modify: `matches/views.py` (`match_detail`)
- Test: `matches/test_match_detail.py`

**Interfaces:**
- Consumes: Tasks 2–5, and #254's `scoring_event_type`.
- Produces: new context keys for Task 7:
  - `top_performers`: `list[TeamLeaders]`, or `[]` unless counted.
  - `movement`: `list[Movement] | None`.
  - `context_rows`: `list[TeamContext]` (always).
  - `h2h`: `HeadToHead` (always).
  - `season_closed`: `bool` (`match.season.state == SeasonState.CLOSED`).
  - `tables`: now `(sheet, rows, totals)` triples; `totals` from `team_totals`, `[]` when not counted.
  - `comparison`: `list[ComparisonRow]`, or `[]` unless counted.
  - `markers`: `[map_marker(match.facility)]` when the facility `is_active and has_location`, else `[]`.
  - `standings_url`: `matches:season_standings` for the season, plus `?division=<pk>` when the home team has a division.
- `select_related` gains `"scorekeeper"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_context_final(self):
    self.score(stats={self.key(self.home, self.alex): 2}, played=[self.pair(self.home, self.alex)])
    ctx = self.get().context
    self.assertEqual(ctx["top_performers"][0].leaders[0].player, self.alex)
    self.assertEqual(len(ctx["movement"]), 2)
    self.assertEqual(ctx["tables"][0][2], [0, 2])  # Assist, Goal (name order)

def test_context_scheduled_and_cancelled(self):
    # unscored: movement None, top_performers [], comparison [], context_rows has 2
    # cancelled: same

def test_score_correction_flips_movement(self):
    # save 2-1, then 1-2 through self.save; second response: home direction differs

def test_query_count_fixed(self):  # replace the existing one
    small = self.scored_match(2); large = self.scored_match(20)
    # also add 30 other scored matches in the season before measuring `large`
    ...
    self.assertLessEqual(expected, 16)   # B + 2, B = 14 from Task 0
    with self.assertNumQueries(expected):
        self.client.get(self.url(large))
```

Keep `scored_match` as it is. Add a helper `extra_results(n)` that creates `n` scored matches between `self.home` and `self.away` on earlier days.

- [ ] **Step 2: Run them to make sure they fail**

Run: `python manage.py test matches.test_match_detail`
Expected: FAIL, `KeyError: 'top_performers'`.

- [ ] **Step 3: Build the context in `match_detail`**

Call `season_teams` and `season_results` once each, and `scoring_event_type` once only when counted and `event_types` is not empty. Update `match_detail.html`'s loop to unpack `sheet, rows, totals` so the page still renders.

- [ ] **Step 4: Run the tests**

Run: `python manage.py test matches`
Expected: PASS. `test_query_count_fixed` passes with `expected <= B + 2`.

- [ ] **Step 5: Commit**

```bash
git add matches/views.py matches/templates/matches/match_detail.html matches/test_match_detail.py
git commit -m "#255: Match page context for the new sections"
```

---

### Task 7: Templates, CSS and DESIGN.md

**Files:**
- Modify: `matches/templates/matches/match_detail.html`
- Create: the six partials in `matches/templates/matches/detail/`
- Modify: `static/css/playnyu.css`, `docs/DESIGN.md`
- Test: `matches/test_match_detail.py`

**Interfaces:**
- Consumes: Task 6 context keys only.

- [ ] **Step 1: Write the failing tests**

```python
def test_top_performers_card(self):
    # alex 2 goals -> "Lee" and "2 Goal" in the card; title has "Alex Lee"
    self.assertContains(response, "Top performers")

def test_movement_card(self):
    self.assertContains(response, "ti-arrow-up")
    self.assertContains(response, "Up 1 place")  # visually-hidden words
    self.assertContains(response, reverse("matches:season_standings", args=[self.season.pk]))

def test_first_result_text(self):
    self.assertContains(response, "First result")

def test_totals_row(self):
    self.assertContains(response, "Team totals", count=2)

def test_comparison_bars(self):
    self.assertContains(response, "pn-bar-away")
    self.assertContains(response, 'aria-hidden="true"')

def test_form_chips_link_and_current(self):
    # an earlier scored match: its chip links to matches:detail; this match's chip has aria-current="page"

def test_head_to_head_empty(self):  # unscored match, no meetings
    self.assertContains(response, "First meeting this season.")

def test_final_standings_label_closed_season(self):
    self.assertContains(response, "Final standings")

def test_venue_map_and_address(self):
    # field with lat/lng and address: json_script "pn-map-markers", leaflet partial, address text
def test_inactive_venue_no_map_no_link(self):
    self.assertNotContains(response, "pn-map-markers")
    self.assertNotContains(response, reverse("facilities:detail", args=[self.field.pk]))

def test_scorekeeper_name_no_email(self):
    # keeper with no name: "PlayNYU player" shows, keeper.email does not
def test_scorekeeper_not_assigned(self):
    self.assertContains(response, "Not assigned")

def test_scheduled_hides_result_sections(self):
    for text in ("Top performers", "Team comparison", "Team totals", "ti-arrow-up"):
        self.assertNotContains(response, text)
    self.assertContains(response, "Season so far")

def test_no_nested_links_final(self):
    collector = LinkCollector(); collector.feed(response.content.decode())
    self.assertFalse(collector.nested)
```

Check `LinkCollector`'s attribute name in the file before you use it.

- [ ] **Step 2: Run them to make sure they fail**

Run: `python manage.py test matches.test_match_detail`
Expected: FAIL on "Top performers" and the other new text.

- [ ] **Step 3: Write the partials and the page layout**

Follow the spec's "Templates" sketches, "By status" table and section order. Fixed copy: "Top performers", "Standings", "Season so far", "Final standings", "Head-to-head", "First meeting this season.", "Team comparison", "Team totals", "Venue", "Scorekeeper", "Not assigned", "First result", "No change", "Full standings". The movement `visually-hidden` text: "Up N place(s), from 5th to 3rd in East" (`ordinal` filter; "of the season" with no division). The map follows DESIGN.md "Maps (Leaflet)": `map_styles.html` in `head` and `json_script` plus `map_assets.html` in `scripts`, only when `markers`.

- [ ] **Step 4: Add the CSS and DESIGN.md entries**

In `static/css/playnyu.css` under `/* Match page */`: `--pn-series-2: #a78bce;` in `:root`, `.pn-bar-away { background-color: var(--pn-series-2); }`, `.pn-form-chip` (min width and height 1.75rem; min-height 40px below 768px). In `docs/DESIGN.md`: the items in the spec's "`docs/DESIGN.md`" list.

- [ ] **Step 5: Run the tests**

Run: `python manage.py test matches facilities`
Expected: PASS.

- [ ] **Step 6: Check 375px by hand**

Run the dev server (`python manage.py runserver`) with seeded data (`python manage.py seed_class_league && python manage.py seed_match_details`). Open a final match, an upcoming match and a cancelled match at 1280px and 375px. Expected: no horizontal page scroll (`document.documentElement.scrollWidth === document.documentElement.clientWidth`), the map tiles load, each form chip is at least 40px tall on the phone. Take before/after screenshots for the PR.

- [ ] **Step 7: Commit**

```bash
git add matches/templates static/css/playnyu.css docs/DESIGN.md matches/test_match_detail.py
git commit -m "#255: Richer match page sections and design docs"
```

---

### Task 8: CI checks

**Files:** none, unless a check fails.

- [ ] **Step 1: Format check**

Run: `black --check .`
Expected: `All done!` and no file "would be reformatted". If one would be, run `black .` and commit.

- [ ] **Step 2: Lint**

Run: `flake8 .`
Expected: no output.

- [ ] **Step 3: Tests with coverage**

Run: `coverage run manage.py test`
Expected: `OK`, no failures or errors.

- [ ] **Step 4: Coverage floor**

Run: `coverage report --fail-under=80`
Expected: exit code 0.

- [ ] **Step 5: No migrations**

Run: `python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

- [ ] **Step 6: Commit any fixes**

```bash
git add -A
git commit -m "#255: Formatting and lint fixes"
```

Skip this step when `git status` is clean.
