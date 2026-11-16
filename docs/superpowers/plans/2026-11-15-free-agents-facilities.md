# Public free agent list and facility schedules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Any signed-in user sees the free agent pool on `teams:free_agent_pool`, and the upcoming games, recent results and a few stats on `facilities:detail`.

**Architecture:** Both features add context to existing views. No new URLs and no migrations. The free agent list is a GET-filtered, paginated card on the pool page. The facility schedule comes from a new `facility_schedule()` helper in `matches/schedule.py`, next to `team_schedule()`. It renders with `components/match_row.html` and a new `facility_page` flag.

**Tech Stack:** Django 5 templates, Tabler (Bootstrap 5), Django `TestCase`, `coverage`.

**Spec:** `docs/superpowers/specs/2026-11-15-free-agents-facilities-design.md`

## Global Constraints

- Branch: `nihal/free-agents-facilities`, from `origin/testing`. Never commit to `main` or `testing`.
- No commit footer or co-author line that names Claude.
- No migrations. No new URL patterns. Every view stays `@login_required`.
- No email, N number or NetID on either page. Name display: `get_full_name|default:"PlayNYU player"`.
- Both lists show 20 rows per page. Recent results show 5 rows at most.
- No "Message" link, no invite button, no "next open slot", no "busiest day" stat, no calendar grid.
- In `templates/components/match_row.html`, change only the facility part of the meta line (after `·`). Don't change the team line. The match PR edits it.
- Follow `docs/DESIGN.md`. Record new components and recipes there in the same PR.
- CI: `black --check .`, `flake8 .`, `coverage run manage.py test`, `coverage report --fail-under=80`.

## Review Focus

1. A filter value from an old bookmark (a closed season, a deleted division, `?season=abc`) must give a 200 and drop only that filter. Task 1 tests this.
2. A division from season A with `?season=B` must not filter to zero rows silently. The form drops the division. Task 1 tests this.
3. A match that starts at 23:30 New York time must group under that local day, not the UTC day. Task 3 tests this.
4. A cancelled game must not be "Next game" and must not count in the stats. It still shows in the list with its badge. Tasks 3 and 5 test this.
5. Query counts must not grow with the number of rows on either page. Tasks 2 and 5 test this.

---

### Task 0: Branch

- [ ] **Step 1: Create the branch**

```bash
git fetch origin && git checkout -b nihal/free-agents-facilities origin/testing
```

Expected: `Switched to a new branch 'nihal/free-agents-facilities'`.

---

### Task 1: `FreeAgentFilterForm`

**Files:**
- Modify: `teams/forms.py` (add after `FreeAgentRequestForm`)
- Test: `teams/test_free_agent_list.py` (create)

**Interfaces:**
- Produces: `FreeAgentFilterForm(data=None)`, a `forms.Form` with `auto_id="filter_%s"` set in `__init__` defaults. Optional fields `season`, `sport`, `division` (`ModelChoiceField`, `required=False`). Method `filter(queryset) -> QuerySet` applies each field that cleaned, and ignores any that didn't.
- `season` queryset: `Season.objects.allowing(SeasonAction.MATCH_FREE_AGENTS).order_by("start_date", "name")`, `empty_label="All seasons"`, labels from `season_label`.
- `sport`: `Sport.objects.order_by("name")`, `empty_label="All sports"`.
- `division`: `Division.objects.filter(season__in=<season queryset>)`, `empty_label="Any division"`. Choices are grouped by season name, one `<optgroup>` each, like `SeasonFieldsMixin.setup_season_fields`. Don't reuse the mixin: its `clean_sport` makes sport required.
- `clean()`: if both a season and a division cleaned and `division.season_id != season.pk`, drop the division from `cleaned_data`. Don't add an error.

- [ ] **Step 1: Write the failing tests** in `teams/test_free_agent_list.py`, class `FreeAgentFilterFormTests(TestCase)`. Fixtures: `make_season()` from `teams.tests` (open), a second season in `SeasonState.CLOSED`, a `Division` on the open season, and a `Sport`.

```python
def test_ids_do_not_collide_with_the_request_form(self):
    self.assertIn('id="filter_season"', str(FreeAgentFilterForm()["season"]))

def test_closed_and_draft_seasons_are_not_choices(self):
    self.assertNotIn(self.closed, FreeAgentFilterForm().fields["season"].queryset)

def test_invalid_values_are_ignored_one_by_one(self):
    form = FreeAgentFilterForm({"season": "abc", "sport": self.sport.pk})
    qs = form.filter(FreeAgentRequest.objects.all())
    # sport still applies, season does not
    self.assertQuerySetEqual(qs, [self.soccer_request], ordered=False)

def test_closed_season_pk_is_ignored(self): ...      # ?season=<closed.pk> -> unfiltered
def test_division_from_another_season_is_dropped(self): ...  # no error, division not applied
def test_each_filter_narrows(self): ...               # subTest for season, sport, division
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `python manage.py test teams.test_free_agent_list`
Expected: `ImportError: cannot import name 'FreeAgentFilterForm'`

- [ ] **Step 3: Implement `FreeAgentFilterForm`** in `teams/forms.py` to the interface above.

`filter()` reads `self.cleaned_data` after `self.is_valid()`. Fields with errors are missing from `cleaned_data`, so each one drops out by itself.

- [ ] **Step 4: Run the tests and see them pass**

Run: `python manage.py test teams.test_free_agent_list`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add teams/forms.py teams/test_free_agent_list.py
git commit -m "Add the free agent list filter form"
```

---

### Task 2: Free agent list on the pool page

**Files:**
- Modify: `teams/views.py` (`free_agent_pool`, lines 253–303)
- Modify: `teams/templates/teams/free_agent_pool.html`
- Create: `templates/components/pager.html`
- Modify: `docs/DESIGN.md` (§5 Pagination: the pager partial. §6: a "Free agents" recipe)
- Test: `teams/test_free_agent_list.py` (add class `FreeAgentListPageTests`)

**Interfaces:**
- Consumes: `FreeAgentFilterForm` (Task 1).
- Produces:
  - `components/pager.html`, which takes `page_obj`, `querystring` (an urlencoded string without `page`, may be empty) and `label` (the `aria-label`). It renders the §5 Pagination markup only when `page_obj.has_other_pages`. Links are `?{% if querystring %}{{ querystring }}&amp;{% endif %}page=N`. Task 5 uses it too.
  - View context adds `filter_form`, `free_agents` (a `Page`), `querystring`. Keep the existing keys.
  - `FREE_AGENTS_PER_PAGE = 20` in `teams/views.py`.

- [ ] **Step 1: Write the failing tests** (`FreeAgentListPageTests`). Fixtures: open season, viewer `make_user("viewer")`, other player `make_user("alex")` with `first_name="Alex"`, `last_name="Lee"`, and a nameless player `make_user("noname")`. Each has a `FreeAgentRequest` in the open season.

```python
def test_other_players_are_listed(self):          # assertContains "Alex Lee"
def test_own_row_is_highlighted(self):            # response contains 'pn-row-me' once
def test_nameless_player_shows_fallback(self):    # assertContains "PlayNYU player"
def test_no_email_on_the_page(self):              # assertNotContains "alex@nyu.edu", "noname@nyu.edu"
def test_closed_season_requests_are_hidden(self): # request in a CLOSED season not shown
def test_draft_season_requests_are_hidden_from_admins_too(self):
def test_inactive_player_is_hidden(self):         # player.is_active=False -> name absent
def test_bad_filter_gives_200(self):              # ?season=abc and ?season=99999
def test_second_page_keeps_filters(self):
    # 25 requests in one sport; GET ?sport=<pk>&page=2
    self.assertEqual(len(response.context["free_agents"]), 5)
    self.assertContains(response, f"sport={sport.pk}&amp;page=1")
def test_query_count_is_constant(self):
    # CaptureQueriesContext for 5 requests, then for 30 -> equal len
def test_empty_state(self):                       # no requests -> "No free agents yet"
def test_filtered_empty_state(self):              # filter with no match -> "No free agents match these filters."
def test_visibility_notice_on_the_request_form(self):
    self.assertContains(response, "Other players can see your name, sport and division.")
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `python manage.py test teams.test_free_agent_list.FreeAgentListPageTests`
Expected: FAIL. `KeyError: 'free_agents'` or missing content.

- [ ] **Step 3: Implement the view change**

The base query is `FreeAgentRequest.objects.filter(season__in=filter_form.fields["season"].queryset, player__is_active=True).select_related("player", "sport", "division", "season").order_by("requested_at", "pk")`. Pass it through `filter_form.filter()`, then `Paginator(qs, FREE_AGENTS_PER_PAGE).get_page(request.GET.get("page"))`. `querystring`: `request.GET.copy()`, pop `page`, `.urlencode()`.

The POST branch doesn't change. Build `filter_form` from `request.GET` on both GET and POST.

- [ ] **Step 4: Implement the template and the pager partial**

Keep the two existing cards. Add a `<p class="form-hint">Other players can see your name, sport and division.</p>` above "Join the pool".

Add a full-width `col-12` card, as in the spec sketch:
- The header is "Free agents", with `free_agents.paginator.count` "players" in `card-actions` (`pn-num`).
- A `card-body` holds `<form method="get">` with the three selects inline and a `btn btn-outline-secondary` "Filter".
- A `list-group list-group-flush` holds the rows. Each row: `avatar.html` `sm`, a name link `{% profile_url item.player %}` (`{% load teams_extras %}`), and the meta line `{{ item.sport }} · {{ item.division.name|default:"Any division" }} · Requested {{ item.requested_at|date:"M j" }}`. Add `pn-row-me` when `item.player_id == user.pk`.
- Then `{% include "components/pager.html" with label="Free agent pages" %}`.
- Empty state, `ti-users`. With no filters: "No free agents yet" / "No one has asked for placement in these seasons." With any filter in `querystring`: "No free agents match these filters."

Render the filter selects with `{{ filter_form.season|control }}` (`{% load ui %}`), with `form-label` labels. The `season_fields.js` include in `{% block scripts %}` stays as it is. The `filter_` IDs keep it off the filter.

Update `docs/DESIGN.md`. Add the pager partial to §5 Pagination. Add a §6 row: "**Free agents** | Page header → Request placement and Your requests cards → full-width Free agents card: GET filter (season, sport, division), list rows (avatar `sm`, linked name, sport · division · requested date), own row `pn-row-me`, pager in `card-footer`".

- [ ] **Step 5: Run the tests and see them pass**

Run: `python manage.py test teams`
Expected: `OK`. The existing `FreeAgentRequestTests` still pass.

- [ ] **Step 6: Commit**

```bash
git add teams/views.py teams/templates/teams/free_agent_pool.html templates/components/pager.html docs/DESIGN.md teams/test_free_agent_list.py
git commit -m "Show the free agent pool to every signed-in player"
```

---

### Task 3: `facility_schedule` helper

**Files:**
- Modify: `matches/schedule.py`
- Test: `matches/test_schedule.py` (add class `FacilityScheduleTests(ScheduleFixtures)`)

**Interfaces:**
- Produces:
  - `FACILITY_UPCOMING_PER_PAGE = 20` and `FACILITY_RECENT_LIMIT = 5`.
  - `group_by_local_date(matches) -> list[tuple[datetime.date, list[Match]]]`. It keeps the input order and groups by `timezone.localdate(m.starts_at)`.
  - `facility_schedule(facility, user, page_number) -> dict` with the keys:
    - `page_obj`: a `Page` of upcoming matches, including cancelled ones. A match counts as upcoming while `ends_at >= now`.
    - `days`: `group_by_local_date(page_obj.object_list)`.
    - `next_game`: the first scheduled upcoming `Match`, or `None`.
    - `recent`: a list of up to 5 scheduled matches that ended and have both scores, newest first.
    - `upcoming_count`: an int, scheduled only.
    - `semester_count`: an int, scheduled only. `starts_at__date` falls in `current_semester(timezone.localdate())`'s `start_date..end_date`.
    - `sport_counts`: a list of `{"name": str, "count": int}`, scheduled only, by `home_team__sport__name`, ordered `-count, name`.
  - Every query starts from `schedule_matches().filter(facility=facility, season__in=seasons_visible_to(user))`. The two counts come from one `aggregate()`, as in the spec.

- [ ] **Step 1: Write the failing tests.** Use `self.add_match(start=..., ...)` from `ScheduleFixtures`. Facility `self.field`.

```python
def test_upcoming_includes_in_progress_and_cancelled(self):
    playing = self.add_match(start=-1, length=2)
    cancelled = self.add_match(start=5, status=Match.Status.CANCELLED)
    data = facility_schedule(self.field, self.player, None)
    self.assertEqual(list(data["page_obj"]), [playing, cancelled])
    self.assertEqual(data["upcoming_count"], 1)
    self.assertEqual(data["next_game"], playing)

def test_cancelled_is_never_next_game(self): ...
def test_other_facility_is_excluded(self): ...
def test_draft_season_hidden_from_player_shown_to_admin(self):  # use self.make_draft()
def test_recent_is_scored_only_newest_first_max_five(self):     # 7 scored + 1 unscored past
def test_page_two(self):                                         # 25 upcoming -> page "2" has 5; "abc" -> page 1
def test_semester_count_uses_semester_dates(self):
    sem = current_semester(timezone.localdate())
    # one match at sem.start_date 12:00 local, one at sem.end_date + 10 days -> count == 1
def test_sport_counts(self):  # 2 soccer, 1 basketball (self.hoops_team vs another hoops team), 1 cancelled soccer
    self.assertEqual(data["sport_counts"], [{"name": "Soccer", "count": 2}, {"name": "Basketball", "count": 1}])
def test_late_evening_groups_by_local_day(self):
    ny = zoneinfo.ZoneInfo("America/New_York")
    day = timezone.localdate() + datetime.timedelta(days=2)
    start = datetime.datetime.combine(day, datetime.time(23, 30), tzinfo=ny)
    # add match start..start+1h; group_by_local_date(...)[0][0] == day
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `python manage.py test matches.test_schedule.FacilityScheduleTests`
Expected: `ImportError: cannot import name 'facility_schedule'`

- [ ] **Step 3: Implement** `group_by_local_date` and `facility_schedule` in `matches/schedule.py` to the interface above. Order upcoming by `starts_at, pk`, and recent by `-starts_at, -pk`. Import `current_semester` from `teams.semesters`.

- [ ] **Step 4: Run the tests and see them pass**

Run: `python manage.py test matches`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add matches/schedule.py matches/test_schedule.py
git commit -m "Add the facility schedule helper"
```

---

### Task 4: `facility_page` flag on the match row

**Files:**
- Modify: `templates/components/match_row.html` (the meta line only, the part after ` · `)
- Modify: `docs/DESIGN.md` (§5 "Match rows")
- Test: `matches/test_schedule.py` (add class `MatchRowFacilityFlagTests(ScheduleFixtures)`)

**Interfaces:**
- Produces: `{% include "components/match_row.html" with facility_page=True %}`. It shows `{{ match.home_team.sport.name }}` in place of the facility link or name. Without the flag, the output is byte-for-byte the same as now.

- [ ] **Step 1: Write the failing tests.** Render with `django.template.loader.render_to_string("components/match_row.html", {"match": m, "facility_page": True})`.

```python
def test_flag_shows_sport_and_no_facility_link(self):
    self.assertIn("Soccer", html)
    self.assertNotIn(reverse("facilities:detail", args=[self.field.pk]), html)
def test_without_flag_links_the_facility(self):
    self.assertIn(reverse("facilities:detail", args=[self.field.pk]), html)
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `python manage.py test matches.test_schedule.MatchRowFacilityFlagTests`
Expected: `test_flag_shows_sport_and_no_facility_link` FAILS.

- [ ] **Step 3: Implement.** Wrap the existing facility `{% if match.facility.is_active %}…{% endif %}` in `{% if facility_page %}{{ match.home_team.sport.name }}{% else %}…{% endif %}`. Change no other line. In `docs/DESIGN.md` "Match rows", add: "On a facility page, pass `facility_page=True`: the meta line shows the sport in place of the facility."

- [ ] **Step 4: Run the tests and see them pass**

Run: `python manage.py test matches`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add templates/components/match_row.html docs/DESIGN.md matches/test_schedule.py
git commit -m "Let the match row show the sport on facility pages"
```

---

### Task 5: Facility page sections

**Files:**
- Modify: `facilities/views.py` (`facility_detail`)
- Modify: `facilities/templates/facilities/facility_detail.html`
- Modify: `docs/DESIGN.md` (§6: a "Facility" recipe)
- Test: `facilities/test_facility_schedule.py` (create)

**Interfaces:**
- Consumes: `facility_schedule(facility, user, page_number)` and its dict keys (Task 3). `match_row.html` with `facility_page=True` (Task 4). `components/pager.html` (Task 2).
- Produces: `facility_detail` context = the existing `facility` and `markers`, plus every key of `facility_schedule(facility, request.user, request.GET.get("page"))`, plus `querystring=""`.

- [ ] **Step 1: Write the failing tests.** Subclass `matches.test_schedule.ScheduleFixtures`. Facility `self.field`, URL `reverse("facilities:detail", args=[self.field.pk])`.

```python
def test_upcoming_match_listed_under_its_day(self):   # assertContains team names and the day header text
def test_cancelled_shows_badge(self):                 # assertContains "Cancelled"
def test_recent_results_show_score(self):             # scored past match -> "2 – 1"
def test_stats(self):                                 # 3 upcoming -> context["upcoming_count"] == 3; "Next game" card shows its date
def test_no_games_empty_states(self):
    self.assertContains(response, "None scheduled")
    self.assertContains(response, "No upcoming games here")
    self.assertContains(response, "No results yet")
def test_pager_shows_with_more_than_twenty(self):     # 21 upcoming -> 'aria-label="Upcoming game pages"'
def test_sport_counts_render(self):                   # "Soccer" with pn-num count
def test_query_count_is_constant(self):               # CaptureQueriesContext, 2 vs 30 matches -> equal
def test_inactive_facility_still_404(self):
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `python manage.py test facilities.test_facility_schedule`
Expected: FAIL on the missing content.

- [ ] **Step 3: Implement the view change.** Merge the dict into the context. No other view change.

- [ ] **Step 4: Implement the template** to the spec sketch:
- Below the page header, a `row row-cards mb-4` with three `col-6 col-lg-4` stat cards (§5 Stat card):
  - "Next game": `next_game.starts_at|date:"D M j, g:i A"`, or "None scheduled".
  - "Upcoming": `upcoming_count`.
  - "This semester": `semester_count`.
- Then `row row-cards`. In `col-lg-8`:
  - "Upcoming games" card: `card-actions` holds `page_obj.paginator.count`. For each `(day, matches)` in `days`, a `subheader` `{{ day|date:"l, M j" }}` then a `list-group list-group-flush` of `match_row` with `facility_page=True`. Then `pager.html` with `label="Upcoming game pages"`. Empty state `ti-calendar-off`, "No upcoming games here" / "Check back after the next schedule is posted."
  - "Recent results" card: match rows with `facility_page=True`. Empty state `ti-scoreboard`, "No results yet" / "Scores show here after games are played."
  - The existing map card, moved below the lists.
- In `col-lg-4`: the existing Sports card. Under the badges, when `sport_counts` has rows, a "Games by sport" `subheader` and a small list of name and right-aligned `pn-num` count.

Add a §6 row to `docs/DESIGN.md`: "**Facility** | Page header → three stat cards (Next game, Upcoming, This semester; `col-6 col-lg-4`) → `col-lg-8`: Upcoming games grouped by day (`subheader` per day, match rows with `facility_page=True`, pager), Recent results, map → `col-lg-4`: Sports with games by sport".

- [ ] **Step 5: Run the tests and see them pass**

Run: `python manage.py test facilities matches`
Expected: `OK`. The existing `FacilityPageTests` still pass.

- [ ] **Step 6: Check the page by hand.** Run `python manage.py runserver` and open one facility with games and one without. Check at 1280px and 375px: no horizontal scroll, and the stat cards stack two then one.

- [ ] **Step 7: Commit**

```bash
git add facilities/views.py facilities/templates/facilities/facility_detail.html docs/DESIGN.md facilities/test_facility_schedule.py
git commit -m "Show upcoming games, results and stats on facility pages"
```

---

### Task 6: CI checks

- [ ] **Step 1: Format**

Run: `black .`, then `black --check .`
Expected: `All done!` with no files to reformat.

- [ ] **Step 2: Lint**

Run: `flake8 .`
Expected: no output.

- [ ] **Step 3: Tests with coverage**

Run: `coverage run manage.py test`
Expected: `OK`, with no failures or errors.

- [ ] **Step 4: Coverage floor**

Run: `coverage report --fail-under=80`
Expected: exit code 0. The TOTAL is 80% or more.

- [ ] **Step 5: Commit any formatting fixes**

```bash
git add -u && git commit -m "Format"
```

Skip this step if `git status` is clean.

---

## Follow-ups (not in this plan)

- "Message" link on free agent rows to `{% url 'chat:new' %}?to={{ item.player_id }}`. Show it only to a captain of a team in that row's season, and never on the viewer's own row. It needs the chat PR.
- After the match PR merges, check that `match_row.html` has both the `matches:detail` team link and the `facility_page` branch.
- The forum topic list can switch to `components/pager.html`.
