# Match detail page with period scores and player stats

## Intent

Each match gets its own page. A player clicks a match on a schedule and sees the teams, time, place, final score, the score per period (Q1, Q2, ...) and each player's stats. League Admins and the assigned Scorekeeper enter that data on the existing score page.

## Goals

- One page per match at `matches/<pk>/`, linked from every match row.
- Score per period, with the period count and label set per sport.
- Per-player counts for each event type of the sport (Goal, Assist, Rebound, ...).
- Record which players took part in each match.
- One entry page for final score, periods and player stats. It reuses the existing score permissions.
- Standings stay as they are. They still read `Match.home_score` and `Match.away_score`.

## Non-goals

- No live, play-by-play or timed events (no "goal at 23:10").
- No season leaderboards or player totals. The team/player pages spec reads `PlayerStat` for that.
- No new roles. Captains can't enter scores or stats.
- No emails or notifications when stats are saved.
- No JavaScript. The forms work as plain HTML posts.

## Constraints

- Shared contract with the team/player pages spec: names of `Sport.period_count`, `Sport.period_label`, `MatchPeriodScore`, `PlayerStat` and `MatchAppearance` stay fixed. This spec only adds fields.
- When a match has period rows, `home_score` and `away_score` equal their sums. `matches/standings.py` and `needing_score` do not change.
- `Roster` has no history. Leaving a team deletes the row. Stats must keep their own `team` link.
- Every page extends `templates/base.html` and follows `docs/DESIGN.md`. Add the new page recipe there in the same PR.
- CI: `coverage report --fail-under=80`.

## Approaches

- **A. Period and stat tables, sums copied to `Match` (recommended).** Matches the contract. Standings and every existing score check keep working. Player pages query `PlayerStat` with plain `Sum`. Cost: the save path must keep the sums in step, in one transaction.
- B. One `MatchEvent` row per event (player, type, period). Periods and stats both derive from it. Richer, but a scorekeeper types one row per goal, and team scores need a sport-specific rule (a basket is 2 or 3 points). Too heavy for the ask.
- C. JSON fields on `Match` for periods and stats. Smallest change, but no foreign keys, no roster check in the database, and the player pages can't aggregate it. Breaks the contract.

Pick A.

## Data model

### `teams.Sport`

- `period_count`: `PositiveSmallIntegerField(default=4, validators=[MaxValueValidator(10)])`. `0` means the sport has no periods (for example tennis). Addition to the contract: `0` is allowed.
- `period_label`: `CharField(max_length=10, default="Q")`. Shown as `Q1`, `Q2`; a label longer than 2 characters shows with a space (`Half 1`, `Set 2`).
- `SportForm` gets both fields. `teams:manage_sports` only adds sports today, so add `teams:edit_sport` (`sports/<pk>/edit/`, League Admin) and an Edit link on each sport row.
- `Sport.clean` refuses a `period_count` lower than the highest stored regular period. Stored overtime rows count: the highest stored `period` must stay at most `period_count + 2`. Message: "Matches already have scores for period N."
- Labels: period `n <= period_count` shows `{period_label}{n}`. Period `period_count + k` shows `OT{k}` (`OT1`, `OT2`). `Sport.period_name(n)` returns the label.

### `matches.MatchPeriodScore`

- `match`: FK `Match`, `CASCADE`, `related_name="period_scores"`.
- `period`: `PositiveSmallIntegerField`, 1-based. Periods past `Sport.period_count` are overtime. At most 2: `period <= period_count + 2`.
- `home_points`, `away_points`: `PositiveIntegerField`.
- `UniqueConstraint(match, period)`. `CheckConstraint(period >= 1)`. Ordering `["period"]`.

### `matches.PlayerStat`

- `match`: FK `Match`, `CASCADE`, `related_name="player_stats"`.
- `player`: FK user, `CASCADE`, `related_name="match_stats"`.
- `team`: FK `teams.Team`, `CASCADE`, `related_name="player_stats"`.
- `event_type`: FK `teams.EventType`, `PROTECT`, `related_name="player_stats"`. The app has no event type delete page, so this guards Django admin only.
- `value`: `PositiveIntegerField`. A zero is not stored; the form deletes the row.
- `UniqueConstraint(match, player, event_type)`.
- `clean()`: `team` is the home or away team; `event_type.sport_id == match.home_team.sport_id`; the player has a `Roster` row on `team`. The roster check runs only when the row is new or its player or team changes, so stats for a player who later left stay valid.

### `matches.MatchAppearance`

- `match`: FK `Match`, `CASCADE`, `related_name="appearances"`.
- `player`: FK user, `CASCADE`, `related_name="match_appearances"`.
- `team`: FK `teams.Team`, `CASCADE`, `related_name="match_appearances"`.
- `UniqueConstraint(match, player)`.
- `clean()`: same rules as `PlayerStat` (team in the match; roster check only for a new row or a changed player or team).
- A `PlayerStat` with `value > 0` implies an appearance. `save_match_sheet` creates the appearance for it.
- The team/player pages count games played from this model, in counted matches.

### `Match` helpers

- `Match.has_periods`: `period_scores` exist.
- `matches/stats.py`: `save_match_sheet(match, periods, final, stats, played)` writes periods, appearances, stats and the final score in one `transaction.atomic()` with `select_for_update()` on the match. It is the only writer.

## URLs and views

| URL | Name | View | Who |
|---|---|---|---|
| `matches/<pk>/` | `matches:detail` | `match_detail` | Any signed-in user who can see the season |
| `matches/manage/<pk>/score/` | `matches:score` | `record_score` (changed) | League Admin, as today |
| `matches/mine/<pk>/score/` | `matches:submit_score` | `submit_score` (changed) | Assigned Scorekeeper, as today |

### `match_detail`

- `@login_required`. Fetch from `Match.objects.filter(season__in=seasons_visible_to(user))`, so a draft season's match is a 404 for players.
- Load: `select_related("season", "facility", "home_team__sport", "away_team__sport", "scorekeeper")`; `period_scores`; `player_stats` with `player` and `event_type`; current rosters of both teams with `player`; the sport's event types ordered by name.
- Build one stat table per team. Rows are the union of current roster players and players with a stat or appearance for that team in this match. Columns are event types.
- Context flags: `can_record` (League Admin and `match.can_change`) and `can_submit` (assigned scorekeeper with the role and `match.can_submit_score`). Each adds a link to the matching score page.
- `nav_section = "schedule"`.

### Score views

- Keep every existing check in `record_score` and `submit_score`. Replace `ScoreForm` with a "match sheet": `ScoreForm` + `PeriodFormSet` + `PlayerStatForm`.
- `PeriodFormSet`: a `formset_factory` with `period_count + 2` forms, no add/delete. The last 2 forms are overtime (`OT1`, `OT2`) and render blank unless stored. Initial values come from the stored rows.
- `PlayerStatForm`: one `IntegerField(required=False, min_value=0)` per (team, player, event type). Field name `stat-<team_pk>-<player_pk>-<event_type_pk>`. Each player row also has a `BooleanField(required=False)` named `played-<team_pk>-<player_pk>`, label "Played". Players are the current roster plus players who left the team but have a stored stat or appearance. Those leavers show as read-only text, and the view keeps their stored values.
- On a valid POST, call `save_match_sheet`, add the message "Saved the score for {match}.", and redirect to `matches:detail`. This changes today's redirect to My matches and Manage matches.
- The page also links back to the match detail page, not the list.

## Validation

- Periods: either every regular period is blank, or every one has a value. Error on the formset: "Enter every period, or leave them all blank."
- Overtime: each overtime row is blank or complete. `OT2` needs `OT1`. Overtime needs the regular periods. Errors: "Enter both teams' points.", "Enter OT1 before OT2.", "Enter the regular periods before overtime."
- A final score alone is allowed for a sport with periods.
- With periods filled: the final score is the sum of all periods, overtime included. The view ignores submitted final values. The final score fields stay editable (no JavaScript) and have the help text "When you enter periods, the final score is their total."
- With periods blank: both final scores are required. Error: "Enter both scores, or every period." Saving deletes any stored period rows.
- Stats: blank or `0` deletes the row. Negative values fail with Django's message. Every valid save has a final score, so stats never exist without one.
- Played: checked creates a `MatchAppearance`. Unchecked deletes it, unless the player has a stat above 0. Then the view keeps the appearance and checks the box on the next render.
- A player appears for one team per match. A player who switched teams shows under both, but Played for both fails: "{name} can only play for one team."
- A sport with `period_count = 0` shows no period section. A sport with no event types shows no stat section.
- Keep `Match.clean` rules: both scores or neither, and no score on a cancelled match.

## Templates

### `templates/components/match_row.html`

- Wrap the "Home vs Away" line in `<a class="text-reset" href="{% url 'matches:detail' match.pk %}">`. The facility link and the action button stay separate links. Do not use `stretched-link`, because the row already has two other links.
- `matches/_my_match_row.html` gets the same link.
- This covers the season schedule, team pages, dashboard panels and the overview, because they all include the row.

### `matches/templates/matches/match_detail.html`

```
Page header
  subheader: Fall 2026 Basketball · Tandon
  h1:        Violets vs Bobcats
  page-meta: Sat Nov 14, 3:00 PM – 4:30 PM · Palladium Gym (link if active)
  right:     [Record score] (btn-primary, only with can_record or can_submit)

Scoreboard card
  [logo xl] Violets (link)    78 – 71    Bobcats (link) [logo xl]
            badge: Final | Scheduled | Cancelled (bg-secondary-lt) | Awaiting score (bg-yellow-lt)

Periods card (only with period rows)
  table card-table:  Team | Q1 | Q2 | Q3 | Q4 | OT1 (only if stored) | T
                     Violets  20  18  22  18  78 (bold)
                     Bobcats  15  20  16  20  71

row: col-lg-6 per team
  Card "Violets"  card-actions: "8 players"
    table: Player | Goal | Assist | ...   (short headers with title=)
      [avatar sm] Alex Lee (profile link if active)   2   1
      [avatar sm] Sam Kim  badge "Left team"          1   0
      [avatar sm] Jo Park  badge "Did not play"       (no numbers)
    empty state: "No players on this roster."
```

- Names show `get_full_name`, else "PlayNYU player". The page and the score form never show an email.
- After a result, a rostered player with no `MatchAppearance` shows `badge bg-secondary-lt` "Did not play" and no numbers.
- `pn-row-me` on the viewer's own row. All numbers `pn-num text-end`. A blank stat shows `0` in `text-secondary`.
- Before a result: the stat tables show the rosters with no number columns, and the line "Stats appear after the score is in."
- Cancelled: no score, no periods, no stat columns. Rosters still show.

### `matches/templates/matches/score_form.html`

The stat grid is too wide for `pn-auth`. Move the page to `container-xl`:

```
Page header: subheader season, h1 "Record the score", meta "Home vs Away · time"
Overwrite warning (alert-warning text-body), as today
col-lg-4: card "Final score"  (two inputs, help text about periods)
          card "Periods"      (table: Period | Home | Away, one row per period, then OT1, OT2 blank)
col-lg-8: one card per team   (table: Player | Played | <event types>; checkbox, number inputs)
Footer: [Save score] (btn-primary)  [Cancel] (ghost, to match detail)
```

- Number inputs use `form-control form-control-sm pn-num text-end` through the `control` filter, with `aria-label="Alex Lee, Goal"`. The checkbox uses `form-check-input` with `aria-label="Alex Lee played"`.
- The tables scroll inside `table-responsive` at 375px.

### `docs/DESIGN.md`

- Add page recipes for "Match" and "Record the score".
- In "Match rows", say the matchup links to the match page.

## Permissions

- Detail page: signed in, and the season is visible (`seasons_visible_to`). No role needed. Draft seasons are 404 for players.
- Entry: unchanged rules. League Admin through `record_score` (`can_change`). Assigned Scorekeeper with the role through `submit_score` (`can_change` and `has_started`).
- Closed season or cancelled match: the detail page shows, with no entry button. The score URLs redirect with the existing messages.
- The detail page shows the "Record score" button only when the same check as the view passes. A League Admin gets `matches:score`. A scorekeeper gets `matches:submit_score`.

## Tests

Put them in `matches/test_match_detail.py` and `matches/test_match_sheet.py`, following the `make_user` style of `test_perm_sweep_matches.py`.

- Models: unique constraints (stats and appearances); overtime limit `period_count + 2`; `MatchPeriodScore.period >= 1`; `PlayerStat.clean` refuses a non-roster player, a team not in the match, and an event type of another sport; an unchanged stat for a player who left still saves.
- `Sport.clean` refuses a lower `period_count` below stored periods. Deleting an in-use event type raises `ProtectedError`. `teams:edit_sport` saves both period fields; casual player 403.
- `save_match_sheet`: sums (overtime included) equal the final score; a stat above 0 creates an appearance; unchecking Played keeps an appearance with stats; blank periods delete rows; zero stats delete rows; one transaction (an error leaves nothing written).
- Detail view: anonymous 302 to login; casual player 200; draft season 404 for a player and 200 for a League Admin; no email in the HTML and "PlayNYU player" for a player without a name; "Did not play" for a rostered player with no appearance; OT column only when stored; period table hidden with no periods; stat columns hidden for a sport with no event types; cancelled match has no score; "Left team" row shows; button shows for the admin and the assigned scorekeeper only.
- Score views: partial periods fail; OT2 without OT1 fails; overtime without regular periods fails; final score alone saves for a sport with periods; periods override submitted final score; blank periods with a blank final score fail; non-assigned scorekeeper 403; cancelled and closed-season redirect as today; redirect goes to `matches:detail`.
- Standings: a match scored by periods counts the same as one scored by final score.
- Match row: links to `matches:detail` on the season schedule and team page.
- Update existing `test_scorekeeping.py` and `test_results.py` assertions for the new redirect.

## Left to the builder

- Wording of help text and empty states.
- Query shape, as long as the detail page uses a fixed number of queries (assert with `assertNumQueries`).

## Decisions

The user answered the open questions on 2026-11-15:

1. Overtime: allow up to 2 extra periods, labelled `OT1` and `OT2`.
2. A final score alone is allowed when a sport has periods.
3. Who played: a "Played" checkbox, stored as `MatchAppearance`.
4. The name fallback everywhere is "PlayNYU player".
