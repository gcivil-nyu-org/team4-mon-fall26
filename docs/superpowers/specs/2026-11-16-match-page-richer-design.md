# Richer match page (#255)

## Intent

The match page (`matches:detail`, spec `2026-11-15-match-detail-stats-design.md`) shows the score, the periods and each player's stats. Players want the story around the result: who starred, how the teams compare, where each team stands, and how this match moved the table. This spec adds five sections to that page. It adds no model and no migration.

The work starts after PR #254 (`nihal/scoring-event-types`) merges. It uses `EventType.is_scoring` and `scoring_event_type(sport)` from that PR.

## Goals

1. **Top performers:** one card at the top with each team's leader for each stat, with avatars ("Lee 24 Points · Kim 8 Rebounds").
2. **Team context:** each team's season record and position, its last 5 results as W/D/L chips that link to those matches, and this season's head-to-head.
3. **Box score totals:** a totals row in each team's stats table, and a side-by-side team comparison with CSS bars.
4. **Venue and officials:** a small map, the address, a link to the venue page, and the scorekeeper's display name.
5. **Standings movement:** the standings table after this match, with both teams tinted and a ▲/▼/–/New marker for each (see Decisions, 6).
6. The page stays at a fixed number of queries, whatever the roster size or the season size.

## Non-goals

- No new models, fields or migrations. No stored standings snapshots: every number is computed on each request.
- No charting library. DESIGN.md allows Chart.js only "on pages that show charts". These bars are Tabler `progress` bars, which DESIGN.md already allows (inline `width` on `.progress-bar`).
- No all-time or cross-season head-to-head. Teams belong to one season, so "head-to-head" is this season only.
- No change to the score form, the standings rules or `rank_rows` tie-breaking.
- No new permissions. Anyone who can open the match page sees every section.
- No play-by-play, no per-period stats, no "player of the match" vote.

## Constraints

- Every page extends `templates/base.html` and follows `docs/DESIGN.md`. Update the "Match" recipe in the same PR.
- Names come from `core.names.display_name` (or the `display_name` filter). The page never renders an email.
- Standings rules stay in `matches/standings.py`: a match counts when it is not cancelled and both scores are set (`counted_matches()`); win 3, draw 1; sort by points, then wins, then team name.
- `Match.clean` keeps both teams in the match's season. So every match of a team is in that team's season, and every team in the season is visible when the match is visible. The new sections need no extra visibility filter.
- PR #253 (`nihal/schedule-table`) may merge first. It renames `matches:schedule_seasons` to `matches:schedule`. This page links to `matches:season_standings` only, so the rename does not touch it.

## Approaches

- **A. Two season-wide queries, then pure Python (recommended).** Load the season's teams (1 query) and the season's counted results as tuples (1 query, `values_list`). Compute current standings, both teams' last 5, the head-to-head and the before/after standings from that one list, with `rank_rows`. Top performers, totals and the comparison reuse the `team_sheets()` data the page loads today (0 queries). The venue and the scorekeeper come through `select_related` (0 queries). Cost: the results list grows with the season (a class league has under 200 matches). The query count does not.
- B. One ORM query per section: `standings_by_team()` for positions (2 queries), a query per team for form, a query for the head-to-head, `compute_standings` twice for before/after (4 queries), and DB `Sum` aggregates for totals. Simple to read, but about 10 extra queries, the same rows read 4 times, and before/after needs a date filter that `compute_standings` does not take.
- C. Store a standings snapshot per match (new model, written by `save_match_sheet`). Fast reads, but it needs a migration, a backfill, and a rewrite of every snapshot after a score correction or a reschedule. Too heavy, and wrong after edits unless every writer keeps it in step.

Pick A.

## Sections

All new code lives in `matches/match_context.py` (team context, head-to-head, standings movement) and `matches/stats.py` (top performers, totals, comparison). The view calls them once each. "Results" below means the list from `season_results(match)`:

```
Result = NamedTuple(pk, starts_at, home_id, away_id, home_score, away_score)
season_results(match) -> list[Result]
    counted_matches().filter(season_id=match.season_id)
        .order_by("starts_at", "pk").values_list(...)          # 1 query
season_teams(match) -> list[Team]
    Team.objects.filter(season_id=match.season_id)
        .select_related("division").order_by("name")            # 1 query
```

The order key of a match is `(starts_at, pk)`. It matches `Match.Meta.ordering`.

### 1. Top performers

- **Data:** `team_sheets(match)` (loaded today), `event_types` (loaded today), and `scoring_event_type(match.home_team.sport)` from #254.
- **Computation:** `top_performers(sheets, event_types, scoring) -> list[TeamLeaders]`, one per team, home first.
  - Event type order: the scoring type first, then the rest by name (the `event_types` order). At most 3 event types per team (see Decisions).
  - For each team and event type: the row with the highest value. A value of 0 (missing) never leads. A tie goes to `_name_key` (named players first, then name, then pk), the same rule as the #253 schedule column.
  - Rows include players who left the team. Their stats keep their `team` link, so they still lead.
  - An event type with no value above 0 for that team is left out for that team.
  - `Leader = (player, value, event_type)`. The card shows the avatar `xs`, the short name (last name, else `display_name`), the value and the event type name: "Lee 24 Points". The full `display_name` goes in the link `title` and in a `visually-hidden` span.
- **Queries:** 0. `scoring_event_type(sport, event_types)` picks from the loaded list (see Decisions).
- **Shown when:** the match is counted (has a result, not cancelled) and one or more leaders exist. Otherwise the card is not rendered.
- **Edge cases:**
  - No stats: no card.
  - No event types for the sport: no card.
  - No scoring type (#254 returns `None`): the order is by name only.
  - Volleyball (score is sets won): leaders come from whatever event types it has (Kills, Aces). The page never claims that a stat total equals the score.
- **Privacy:** `display_name` only. The profile link only for an active user, as in the stat tables today.

### 2. Team context

- **Data:** `season_teams(match)` and `season_results(match)`.
- **Computation:** `team_context(match, teams, results) -> list[TeamContext]`, home first. The section shows the season **today**: every counted result, including matches after this one. It is labelled "Season so far", or "Final standings" when the season is closed. (The standings-movement section shows the table at the time of this match.)
  - **Record and position:** `rank_rows(teams, results)`, then `positions(rows)`, a new helper in `matches/standings.py` extracted from the loop in `standings_by_team`. Shows "5–1–2 · 17 pts" and "2nd of 8", plus "1st in East" when the team has a division. With 0 played: record "–", position "–".
  - **Last 5:** the team's 5 newest results by order key, newest first. Each chip is `Form(result_pk, letter, team_score, opponent_score, opponent, starts_at, is_this_match)`. The letter is W, D or L from the team's side. The chip links to `matches:detail` of that match. The chip for this match gets `aria-current="page"` and no link.
  - **Head-to-head:** results where `{home_id, away_id} == {match.home_team_id, match.away_team_id}`, this match included when counted. Shows "Violets 2 · Draws 1 · Bobcats 0" and one line per meeting (date, score, link). With no meetings: "First meeting this season."
- **Queries:** +2 (teams, results). Shared with section 5.
- **Shown when:** always, for every status. For an upcoming match this is the preview.
- **Edge cases:**
  - Closed season: same numbers, label "Final standings".
  - Draft season: only League Admins reach the page. Same rules.
  - Team with no division: season position only.
  - Cancelled matches never appear in form or head-to-head (not counted).
  - A result whose opponent is not in `teams` cannot happen (`Match.clean`), but the code skips it, like `rank_rows`.
- **Privacy:** team data only. No people.

### 3. Box score totals and team comparison

- **Data:** `tables` and `event_types` (loaded today).
- **Computation:**
  - `team_totals(sheet, event_types) -> list[int]`: for each event type, the sum of `row.stats.get(pk, 0)` over every row of the sheet, players who left included. It matches what the table rows show.
  - The totals row is a `<tfoot>` row: "Team totals", then one bold `pn-num text-end` cell per event type.
  - `comparison_rows(home_totals, away_totals, event_types) -> list[ComparisonRow]` with `ComparisonRow(event_type, home, away, home_pct)`. `home_pct = round(100 * home / (home + away))`. A row where both are 0 is left out. The scoring type comes first (same order as section 1).
  - The comparison card: one row per event type, "12 · Rebounds · 9", the larger number `fw-bold`, then one `progress` with two `progress-bar` segments (home `bg-primary`, width `home_pct`%; away `pn-bar-away`, width `100 - home_pct`%). The bars are `aria-hidden="true"`; the numbers are the text version (DESIGN.md: "Always put a text version of the key number next to the chart").
- **Queries:** 0.
- **Shown when:** the match is counted and the sport has event types. The comparison card also needs one row with a total above 0.
- **Edge cases:**
  - No stats: the totals row shows zeros in `text-secondary`. No comparison card.
  - No event types: no stat columns today, so no totals row and no comparison.
  - A player who did not play: their row shows no numbers today. They add 0 to the totals.
  - Volleyball: totals of its own event types. No link to the score.
- **Privacy:** no names in this section.

### 4. Venue and officials

- **Data:** `match.facility` (already `select_related`) and `match.scorekeeper` (add to `select_related`).
- **Computation:**
  - `map_marker(facility)` moves from `facilities/views.py:_map_marker` to `facilities/maps.py` as a public function. `facilities/views.py` imports it. `markers = [map_marker(facility)]` only when the facility `is_active` and `has_location`. An inactive facility has no public page, and `facility_map.js` always makes the popup a link.
  - Venue lines: the name (a link to `facilities:detail` when active), the address and the borough (same format as the facility page header).
  - Officials: "Scorekeeper" and the avatar `xs` plus `display_name(match.scorekeeper)`. No profile link and no email. With no scorekeeper: "Not assigned".
- **Queries:** 0. Leaflet loads from the pinned CDN partials (`components/map_styles.html` in `head`, `components/map_assets.html` and `json_script` in `scripts`), only when `markers` is not empty.
- **Edge cases:**
  - No coordinates: no map. The address lines still show.
  - No address and no borough: only the name.
  - A scorekeeper who lost the role: the name still shows. The model keeps the link "so past matches stay accurate".
  - An inactive scorekeeper account: the name still shows (`display_name` does not check `is_active`).
- **Privacy:** `display_name` only. The facility name goes into the marker as text; `facility_map.js` sets it with `textContent`.

### 5. Standings movement

- **Data:** the same `season_teams` and `season_results` as section 2.
- **Computation:** see the next section. `standings_movement(match, teams, results) -> list[Movement] | None`, home first.
- **Queries:** 0 more (shares section 2's 2 queries).
- **Shown when:** the match is counted. For a scheduled match without a result, an "Awaiting score" match or a cancelled match, the function returns `None` and the card is not rendered. A cancelled match never counts, so it never moves the table.
- **Edge cases:** in the algorithm below.
- **Privacy:** team data only.

## Standings movement algorithm

Definitions:

- `key(m) = (m.starts_at, m.pk)`.
- **Before** = every counted match of the season with `key < key(this match)`. This reads "ended before" as "came before this match in the season's order". Two reasons. (1) Matches at the same time on other courts have no clear order by end time; the start time plus pk gives one strict order. (2) With a strict order, the "after" table of one match is the "before" table of the next match, so the movements of a season chain together.
- **After** = Before plus this match.
- Matches after this one never change Before or After. A later score correction to this match, or a reschedule, changes the numbers on the next page load. Nothing is stored.

Steps:

1. If `not match.has_result or match.is_cancelled`: return `None`.
2. `before_rows = rank_rows(teams, [r for r in results if (r.starts_at, r.pk) < key])`.
3. `after_rows = rank_rows(teams, [r for r in results if (r.starts_at, r.pk) <= key])`. This includes this match, because it is counted.
4. `before = positions(before_rows)`, `after = positions(after_rows)`. `positions` gives each team its season `position` and `of`, and `division_position` and `division_of` when it has a division.
5. For each of the two teams, choose the table:
   - The team has a division: use the division table (`division_position`, `division_of`, label = the division name). This is the table a division's players follow.
   - No division: use the season table (`position`, `of`, label = "the season").
   - The two teams can use different tables. In a cross-division match each team shows its own division.
   - Records in a division table count every season match, cross-division ones too. This is the rule of `compute_standings(season, division)` today.
6. `change = before_position - after_position`.
   - `change > 0`: `up`, "▲2" (`ti-arrow-up`, `text-green`).
   - `change < 0`: `down`, "▼1" (`ti-arrow-down`, `text-red`).
   - `change == 0`: `same`, "No change" (`ti-minus`, `text-secondary`).
   - The team had 0 played before this match: `first`, no arrow, the text "First result". Its "before" position comes only from the name tie-break, so a change would mean nothing.
   - A `visually-hidden` span says it in words: "Up 2 places, from 5th to 3rd in East". The colour is never the only signal.
7. Points: "11 → 14 pts (+3)". The points change is `WIN_POINTS`, `DRAW_POINTS` or 0, from this match only.

`Movement = (team, table_label, before_position | None, after_position, of, before_points, after_points, direction, change)`. `before_position` is `None` for `first`.

Rendering: "▲2 (5th → 3rd in East) · 11 → 14 pts". The card footer links to `matches:season_standings` with `?division=<pk>` when the home team has a division.

## Templates

`matches/match_detail.html` stays the page. Each new section is a partial in `matches/templates/matches/detail/`: `_top_performers.html`, `_movement.html`, `_comparison.html`, `_team_context.html`, `_venue.html`. The team tables move to `_box_score.html` with the new `<tfoot>`.

New CSS in `static/css/playnyu.css` under a "Match page" comment: `.pn-bar-away` (background `var(--pn-series-2)`, a new token for `#a78bce`, chart series 2 in DESIGN.md) and `.pn-form-chip` (a fixed 1.75rem square for W/D/L chips, at least 40px touch target through padding on phones).

### Desktop (≥992px)

```
Page header: subheader "Fall 2026 · East"   h1 "Violets vs Bobcats"     [Record score]
             meta "Sat Nov 14, 6:00 PM – 8:00 PM · Pier 40"
+---------------------------------------------------------------------------------+
| [logo xl] Violets            3 – 1   [Final]            Bobcats [logo xl]       |
+---------------------------------------------------------------------------------+
col-lg-8                                             | col-lg-4
+--------------------------------------------+       | +-----------------------------+
| Top performers                             |       | | Standings                   |
| Violets            | Bobcats               |       | | [logo] Violets  ▲2          |
| (A) Lee 2 Goal     | (J) Park 1 Goal       |       | |   5th → 3rd in East         |
| (S) Kim 1 Assist   |                       |       | |   11 → 14 pts (+3)          |
+--------------------------------------------+       | | [logo] Bobcats  ▼1          |
| Periods   Team    Q1 Q2 Q3 Q4  T           |       | |   2nd → 3rd of 8            |
|           Violets  1  0  1  1  3           |       | |   12 → 12 pts               |
|           Bobcats  0  0  1  0  1           |       | | Full standings ->           |
+--------------------------------------------+       | +-----------------------------+
| Team comparison                            |       | | Season so far               |
|   3   Goal    1                            |       | | Violets  5–1–2 · 17 pts     |
|   [██████████████████░░░░░░]               |       | |   2nd of 8 · 1st in East    |
|   2   Assist  0                            |       | |   Last 5 [W][W][D][L][W]    |
|   [████████████████████████]               |       | | Bobcats  4–2–2 · 14 pts     |
+--------------------------------------------+       | |   3rd of 8                  |
                                                     | |   Last 5 [L][W][W][D][W]    |
                                                     | | Head-to-head                |
                                                     | |   Violets 1 · Draws 0 · Bobcats 0
                                                     | |   Nov 14  3–1  (this match) |
                                                     | +-----------------------------+
                                                     | | Venue                       |
                                                     | | [ small map ]               |
                                                     | | Pier 40 ->                  |
                                                     | | 353 West St, Manhattan      |
                                                     | | Scorekeeper (K) Kai Diaz    |
                                                     | +-----------------------------+
row-cards, col-lg-6 each
+--------------------------------------+ +--------------------------------------+
| [logo] Violets            8 players  | | [logo] Bobcats            7 players  |
| Player            Assist  Goal       | | Player            Assist  Goal       |
| (A) Alex Lee         0      2        | | (J) Jo Park          0      1        |
| (S) Sam Kim          1      1        | | ...                                  |
| Team totals          1      3        | | Team totals          0      1        |
+--------------------------------------+ +--------------------------------------+
```

### Phone (375px)

One column, in DOM order. No horizontal page scroll; the stat tables scroll inside `table-responsive`.

```
Header (h1 wraps, Record score under it)
Scoreboard (col-4 each, logos xl)
Top performers (home block, then away block)
Periods (table-responsive)
Team comparison (bars full width)
Standings (two stacked team blocks)
Season so far (form chips wrap; each chip ≥40px tall)
Head-to-head
Venue (map 200px tall, then address and scorekeeper)
Violets box score (table-responsive, totals in tfoot)
Bobcats box score
```

### By status

| Status | Shows |
|---|---|
| Final | All sections |
| Awaiting score / Scheduled | Scoreboard, "Stats appear after the score is in.", Season so far, Head-to-head, Venue, rosters. No top performers, standings, comparison or totals. |
| Cancelled | Scoreboard (Cancelled), Season so far, Head-to-head, Venue, rosters. Nothing that needs a result. |

### Section order (decided)

1. Scoreboard. 2. Standings movement. 3. Top performers. 4. Box score: periods, team comparison, and each team's table with totals. 5. Team context: season so far and head-to-head. 6. Venue and officials. This order replaces the desktop rail sketch above: the sections run in this order at every width.

### What to cut if the page gets too busy

In this order:

1. The team comparison bars. They repeat the totals row in another form.
2. The head-to-head list of meetings. Keep the one-line summary.
3. The map. Keep the venue link and address; the venue page has the map.

Keep standings movement, totals and the scoreboard.

### `docs/DESIGN.md`

- Update the "Match" recipe to the new structure, the rail and the "By status" rules.
- Add "Form chips" under the leaderboard component: `badge` squares, `bg-green` W, `bg-secondary` D, `bg-red` L, letter always shown, link to the match, `title` "W 3–1 vs Bobcats · Nov 2", `aria-current="page"` and no link for the current match.
- Add "Comparison bars": `progress` with two segments, `bg-primary` and `pn-bar-away`, `aria-hidden`, numbers as text.
- Add "Movement": arrow icon, colour, and the words in `visually-hidden`.
- Add `--pn-series-2`, `pn-bar-away` and `pn-form-chip` to "Where things live".

## Performance budget

The view adds a fixed number of queries. It never runs a query per player, per event type, per match of the season or per section.

| Source | Queries | Notes |
|---|---|---|
| Today's page (baseline `B`) | `B` | Measured on the branch before Task 1. The current test only asserts `≤ 20`. |
| `scorekeeper` in `select_related` | +0 | One more join on the match query |
| `scoring_event_type(sport, event_types)` | +0 | Picks from the loaded event types |
| `season_teams(match)` | +1 | `select_related("division")` |
| `season_results(match)` | +1 | `values_list`, no model instances |
| Top performers, totals, comparison | +0 | From `team_sheets` |
| Team context, head-to-head, movement | +0 | From the two lists above |
| Venue, map, officials | +0 | `select_related` and static assets |
| **Total** | **`B + 2`** | Same for every status |

Test: the page has the same query count for 2 and 20 roster players, and for 1 and 30 other season matches. The count is at most `B + 2`. `B` measured 14 on `testing`, so the page runs at most 16.

CPU: `rank_rows` runs 3 times over at most a few hundred tuples. That is well under a millisecond.

## Tests

New `matches/test_match_context.py` (pure functions, `SimpleTestCase` with `SimpleNamespace` teams and `Result` tuples) and new cases in `matches/test_match_detail.py` (view, `SheetFixtures`).

- `positions`: season position, division position and `division_of`; a team with no division gets `None`. `standings_by_team` tests still pass after the extract.
- Movement:
  - "before" excludes a match with the same `starts_at` and a higher pk, and includes one with a lower pk.
  - Matches after this one do not change the result.
  - A win moves a team up ("▲2 (5th → 3rd)"), a loss moves it down, a draw with the same position gives "No change".
  - The first result of a team gives `first`.
  - A division team uses its division table; a team without a division uses the season table; a cross-division match uses each team's own division.
  - Returns `None` for a match without a result and for a cancelled match.
- Team context: record and position; last 5 newest first, capped at 5, W/D/L from each side; the chip for this match has no link; head-to-head counts both home/away orientations and skips other opponents; "First meeting this season." with no meetings; cancelled matches never appear.
- Top performers: scoring type first; tie by name; nameless player sorts after named; a player who left still leads; 0 never leads; no card with no stats; no card with no event types; sport with no scoring type orders by name.
- Totals and comparison: totals include a player who left; totals row shows; both-zero rows left out; `home_pct` rounding (1 vs 2 gives 33).
- Venue: map JSON only for an active facility with coordinates; inactive facility gives no link and no map; address shows; scorekeeper `display_name` shows and the email does not; "Not assigned" without a scorekeeper.
- View by status: final shows every section; scheduled and cancelled show no top performers, no standings card and no comparison; cancelled still shows Season so far; closed season label "Final standings".
- Privacy: no email anywhere on a final match page with a nameless scorekeeper and a nameless player ("PlayNYU player" shows).
- Links: `LinkCollector` finds no nested anchors on the page; every form chip links to `matches:detail`.
- Query count: as in the budget.
- `facilities` tests still pass after `map_marker` moves.

## Decisions

The user approved these on 2026-11-16. They replace the open questions.

1. **Who kept score.** The page shows the assigned scorekeeper, by `display_name`, or "Not assigned". No new field and no migration.
2. **Team context as of today.** Team context shows the season as it is today. It is labelled "Final standings" for a closed season, else "Season so far". Standings movement covers the before and after of this match.
3. **`scoring_event_type` signature.** #256 ships `scoring_event_type(sport)` with 1 query. This PR adds an optional `event_types` argument: with a loaded list, it picks from the list and runs no query. The current callers keep working. The budget is `B + 2`.
4. **Cap on top performers.** At most 3 stats per team: the scoring stat first, then the others by event type order (name). A 0 never leads.
5. **Section order.** Scoreboard, standings movement, top performers, box score, team context, venue. If the page gets busy, cut in this order: the comparison bars, then the head-to-head list, then the map.
6. **Standings movement is a table (changed 2026-11-16, overrides section 5 and "Rendering" below).** The card shows the full standings table as it stood after this match, with the leaderboard columns (#, Team, P, W, D, L, Pts). Both match teams' rows are tinted (`pn-row-match`). Only those two rows get a marker against the table before the match: green "▲N", red "▼N", neutral "–", or "New" for a team's first result. Each marker has `role="img"` and an `aria-label` ("Up 2 places, from 5th to 3rd", "No change, 3rd", "First result, 3rd"). Table choice: the division table when both teams share a division, else the season table (the simpler of the two options; a cross-division match shows the season table). Below 576px, P and D hide, and the table sits in `table-responsive`. No table for an upcoming, awaiting-score or cancelled match. `season_teams` now also selects `sport` (team logos), so the query count stays `B + 2`.
