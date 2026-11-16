# Public free agent list and facility schedules

Status: approved 2026-11-15, with the recommendations. See "Decisions" at the end.

Two small features. Each one is one view change, one template change and its tests. Neither needs a migration.

"Public" means any signed-in user. Every page stays `login_required`. No page shows an email.

Soft dependencies on work from other agents:

- `matches:detail <pk>`: the match page.
- `teams:detail <pk>`: the public team page.
- `chat:new?to=<user_pk>` from the chat work. It opens or reuses the 1:1 chat.

If one of these isn't merged when this work starts, leave out that link and add it in a follow-up. Don't wait for it.

---

## A. Public free agent list

### Intent

Players on `teams:free_agent_pool` see who else is in the pool. Captains see who they could recruit.

### Goals

- A "Free agents" card on the existing page lists every pool request in seasons that still place free agents.
- Filters: season, sport, and division. Division shows only when the chosen season has divisions.
- Each row: avatar `sm`, player name linked to `profiles:detail`, then sport · division (or "Any division") · "Requested Nov 3".
- The name is `get_full_name`, or "PlayNYU player" when it is empty. Never the email.
- The viewer's own row gets `pn-row-me`.
- The "Request placement" form and "Your requests" card stay as they are.

### Non-goals

- No change to League Admin placement (`manage_free_agents`, `match_free_agents`).
- No "add to my team" or invite button. `add_player` needs an email, and the list shows none.
- No "Message" link in this PR. It is a follow-up after `chat:new` lands.
- No player bio, skill level, or position on the row. `FreeAgentRequest` doesn't store them.
- No opt-out flag. Every pool request is listed.

### Approaches

1. **A card on the existing page, with GET filters (picked).** No new URL or nav item. The page already has the season and division dependent selects.
2. A separate page, `teams:free_agent_list`. It gives a clean URL, but splits one task over two pages and needs a link from the nav or the pool page.
3. One tab per sport, like the home standings. Nine tabs plus a season filter is too much. Tabs also can't page their lists without reloads.

### URLs, views, queries

URL: no change. `teams/free-agents/?season=<pk>&sport=<pk>&division=<pk>&page=<n>`.

`free_agent_pool` adds:

- `FreeAgentFilterForm(request.GET or None)` in `teams/forms.py`. It uses `auto_id="filter_%s"`, so its IDs don't collide with the request form's `id_season`, `id_sport` and `id_division`. `season_fields.js` reads those IDs and doesn't touch the filter. The filter needs no JavaScript: its division select uses one `<optgroup>` for each season, and the server ignores a division from another season. It has optional `ModelChoiceField`s:
  - `season`: `Season.objects.allowing(SeasonAction.MATCH_FREE_AGENTS)` (open and active seasons). Draft seasons drop out for everyone. Closed seasons drop out, because their requests are stale.
  - `sport`: all sports.
  - `division`: divisions of the chosen season.
  
  An invalid value is ignored, and the list shows unfiltered. It never gives a 400.
- The query:

  ```python
  FreeAgentRequest.objects.filter(
      season__in=<season field queryset>, player__is_active=True
  ).select_related("player", "sport", "division", "season").order_by("requested_at", "pk")
  ```

  Then apply the cleaned filters.
- `Paginator(qs, 20)`, read from `page` (`get_page`, so a bad page number gives the last page).
- Context: `filter_form`, `free_agents` (the page), `querystring` (the filters without `page`, for pager links).
- The POST branch doesn't change. After a POST with errors, the GET filters are empty, which is fine.

Queries: one count and one page select. The query count stays the same for any page size (test with `assertNumQueries`).

### Captain action (decided: "Message" only, as a follow-up)

| Option | Cost | Risk |
|---|---|---|
| None: the profile link only | Zero | Captains have no way to reach the player |
| **"Message" link to a direct chat (picked)** | One `{% url %}` once chat lands | Spam is possible. Limit who sees the link |
| "Invite to my team" button | New view, invite model or consent flow | Goes around League Admin placement. Repeats the existing TODO in `add_player` about consent |

The follow-up PR adds "Message" (`btn btn-sm btn-ghost-secondary`, `ti-message`) to `{% url 'chat:new' %}?to={{ item.player_id }}`. Show it only when all of these are true:

- The viewer captains a team in that row's season.
- The team isn't full.
- The row isn't the viewer's own.

Build the set of the viewer's season IDs with one query: `Team.objects.filter(captain=user).values_list("season_id")`. Pass it in context. The full-roster check can wait: the link only opens a chat.

This PR ships rows with no action.

### Template sketch

`teams/free_agent_pool.html`: the two existing cards, then a full-width row:

```
[card] Free agents                                   [card-actions: "42 players" pn-num]
  [card-body] GET form inline: Season [All seasons v]  Sport [All sports v]  Division [Any v]  (Filter btn-outline-secondary)
  [list-group-flush]
    (avatar) Alex Lee
             Soccer · Division A · Requested Nov 3
    (avatar) You (pn-row-me)
             Basketball · Any division · Requested Nov 1
  [card-footer pager, only when more than one page; links keep ?season=&sport=&division=]
  [empty] ti-users "No free agents yet" / "No one has asked for placement in these seasons." (filtered: "No free agents match these filters.")
```

The filter is a plain GET form with no script. Add one line to the form's help text: "Other players can see your name, sport and division."

Add a "Free agents" page recipe to `docs/DESIGN.md` §6 in the same PR.

### Permissions and privacy

- `login_required` (as now). All signed-in users see the list.
- Draft seasons are hidden from everyone, because they don't place free agents yet.
- Fields shown: name, avatar initials, sport, division, request date. No email, N number, or NetID. The profile page already hides them.
- Inactive and placeholder users are left out (`player__is_active=True`). `profiles:detail` returns 404 for them.

### Tests (`teams/tests.py` or `teams/test_free_agent_list.py`)

- Another player's request shows. The viewer's own request has `pn-row-me`.
- Requests in a draft season are hidden from a player and from the list for an admin alike, because draft seasons don't place free agents.
- Requests in a closed season are hidden.
- Each filter narrows the list: season, sport, and division.
- An invalid filter value (`?season=abc`, `?season=99999`) gives a 200 and an unfiltered list.
- Page 2 shows rows 21–40. Pager links keep the filters.
- No email appears in the response (`assertNotContains(player.email)`).
- An inactive user is not listed.
- The query count is constant for 5 and 30 requests.
- A player with no name shows as "PlayNYU player".
- The request form shows the visibility notice.
- (Follow-up PR) The "Message" link shows only for a captain of a team in that season, and never on the viewer's own row.
- The existing POST and cancel tests still pass.

---

## B. Facility schedule and stats

### Intent

`facilities:detail` tells a player what happens at a venue: the next games, recent results, and how busy it is.

### Goals

- Upcoming games at this facility, grouped by date. Each row shows both teams, the time, the sport, and a link to the match page.
- Recent results: the last 5 scored games.
- A stat row of three cards: Next game, Upcoming games, Games this semester.
- The Sports card shows the sports listed for the facility. It also shows a game count for each sport played here.

### Non-goals

- No calendar grid.
- No "next open slot". `Facility` has no opening hours, so "open" has no definition. Decided: skip.
- No "busiest day/time" stat (see the table below).
- No booking or schedule changes from this page.

### Approaches

1. **Sections on the detail page: a list grouped by date, with pagination (picked).** It reuses `match_row.html` and the existing recipes, and it works on a phone.
2. A week grid (7 columns × hours). Most cells are empty for a venue with a few games a week. It needs new CSS and a week picker, and it doesn't fit at phone width.
3. A preview on the detail page, plus a new `facilities:schedule <pk>` page with the full list. That is one more URL and template for a list that fits on one page with a pager.

### Stats: worth it or noise

| Stat | Verdict | Why |
|---|---|---|
| Next game (date and time) | Keep | The most useful fact. One `first()` query |
| Upcoming games (count) | Keep | One aggregate. Shows whether the venue is in use |
| Games this semester | Keep | One aggregate. "This semester" means `starts_at` from `current_semester(today).start_date` to `end_date`. `Season.term` is set only on default seasons, so it can't be used |
| Games per sport | Keep, inside the Sports card | One `values().annotate()`. Shows which listed sports are really played here |
| Busiest day/time | Drop | Meaningless with fewer than about 20 games, and most venues have fewer |
| Teams that played here | Drop | Noise |
| Next open slot | Drop | Needs opening hours that the model doesn't have |

### URLs, views, queries

URL: no change. `facilities/<pk>/?page=<n>` pages the upcoming list.

`facility_detail` adds (helper `facility_schedule(facility, user)` in `matches/schedule.py`, next to `team_schedule`):

```python
base = schedule_matches().filter(
    facility=facility, season__in=seasons_visible_to(user)
)
now = timezone.now()
upcoming = base.filter(ends_at__gte=now).order_by("starts_at", "pk")
recent = base.scheduled().filter(
    ends_at__lt=now, home_score__isnull=False, away_score__isnull=False
).order_by("-starts_at", "-pk")[:5]
stats = base.scheduled().aggregate(
    upcoming=Count("pk", filter=Q(ends_at__gte=now)),
    this_semester=Count(
        "pk", filter=Q(starts_at__date__range=(sem.start_date, sem.end_date))
    ),
)
per_sport = (
    base.scheduled().values("home_team__sport__name")
    .annotate(n=Count("pk")).order_by("-n", "home_team__sport__name")
)
```

- `upcoming` goes through `Paginator(upcoming, 20)`. Cancelled matches stay in, with the badge, as on the schedule pages. They don't count in the stats.
- Group the page in the view, not with `{% regroup %}`. `regroup ... by starts_at.date` groups by the UTC date, which is wrong near midnight. Build `[(date, [matches])]` with `timezone.localdate(m.starts_at)`.
- "Next game" is `upcoming.filter(status=SCHEDULED).first()`. It is one query, it skips cancelled games, and it is the same on every page.

Queries: about 8 for any number of matches (facility, sports, next game, upcoming count, upcoming page, recent, aggregate, per sport). `Match.facility` already has an FK index. Test the count with `assertNumQueries`.

### Template sketch

`facilities/facility_detail.html`:

```
page header (as now)
[row: 3 stat cards, col-6 col-lg-4]
  Next game: "Sat Nov 21, 2:00 PM" (or "None scheduled")   Upcoming: 12   This semester: 34
[row]
  col-lg-8:
    [card] Upcoming games                                 [card-actions: "12" pn-num]
      [subheader] Saturday, Nov 21
        match_row (facility_page=True)
      [subheader] Sunday, Nov 22
        ...
      [card-footer pager when more than one page]
      [empty] ti-calendar-off "No upcoming games here"
    [card] Recent results
      match_row ×5 with the score (facility_page=True)
      [empty] ti-scoreboard "No results yet"
    [card] map (as now, moved below the lists)
  col-lg-4:
    [card] Sports: badges as now. Each played sport adds a count: "Soccer · 8"
```

`components/match_row.html` gets one optional flag, `facility_page=True`. It shows the sport name in place of the facility link on the meta line, because a link to the page you are on is noise. Record the flag in `docs/DESIGN.md` "Match rows" in the same PR.

The match PR also edits `match_row.html`: it turns "Home vs Away" into a link to `matches:detail`. To keep the merge easy, change only the facility part of the meta line (the text after `·`). Don't touch the team line. Don't pass a "Details" action: the match PR's link replaces it. Team links to `teams:detail` are not part of this PR.

### Permissions and privacy

- `login_required`. Inactive facilities return 404 (as now).
- Matches in draft seasons are hidden from non-admins, through `seasons_visible_to`. League Admins see them, the same as on the schedule pages.
- No people are shown, only teams. Scorekeeper names are not shown.

### Tests (`facilities/tests.py`)

- An upcoming match at the facility shows. A match at another facility doesn't.
- A match in progress (started, not ended) is in Upcoming.
- A draft-season match is hidden from a player and shown to a League Admin.
- A cancelled upcoming match shows the badge and isn't in the stat counts.
- Recent results: only scored matches, newest first, 5 at most.
- Grouping uses the local date. A match at 23:30 America/New_York goes under that day.
- Page 2 of 25 upcoming matches has 5 rows. `?page=abc` gives page 1.
- Stats: the counts are correct. "Next game" shows "None scheduled" when nothing is upcoming.
- Games per sport counts only non-cancelled matches.
- The query count is constant for 2 and 30 matches.
- The empty states render with no matches.
- `match_row` with `facility_page=True` shows the sport and no facility link. Without the flag, the row is unchanged.
- "Games this semester" counts a match inside the current semester's dates and not one outside them.

---

## Coverage

Each feature is one view branch and one helper. The tests above cover every branch. `coverage report --fail-under=80` must still pass.

## Decisions (approved 2026-11-15)

1. List every free agent. Show the visibility notice on the request form. No opt-out field.
2. Captains get only a "Message" link to `chat:new?to=<user_pk>`, in a follow-up PR. No invite button.
3. No "next open slot".
4. A player with no name shows as "PlayNYU player".
5. Keep the `facility_page` change to `match_row.html` to the facility part of the meta line. The match PR edits the team line.
