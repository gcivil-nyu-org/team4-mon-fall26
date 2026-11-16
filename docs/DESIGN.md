# PlayNYU design system

The one source of truth for how PlayNYU looks. Every page follows it, whether a person or a coding agent writes the template. If something you need isn't covered here, add it to this file in your PR rather than inventing it in a template.

**Look:** Airbnb-style cards, spacing and imagery for people and teams, with tight sports-app tables (FotMob/ESPN) for stats and leaderboards. Clean, information-dense, never cluttered.

**Stack:** Django templates + [Tabler](https://tabler.io) (a dashboard kit built on Bootstrap 5) + Tabler Icons. No build step, no JavaScript framework. Chart.js only on pages that show charts.

---

## 1. Principles

1. **Faces and crests first.** People always appear with an avatar, teams always with a logo. Lists of names without images are not allowed.
2. **Dense, not cramped.** Show more per screen by using tight rows and small secondary text, not by shrinking padding inside cards or removing whitespace between sections.
3. **One accent.** NYU violet is the only brand color. Everything else is neutral gray, plus green/red/amber only for status.
4. **One primary action per screen.** At most one solid violet button in view. Everything else is outline, ghost or a link.
5. **Numbers line up.** Every number in a table, stat or leaderboard uses tabular figures and is right-aligned.

## 2. Page setup

Every page extends `templates/base.html` and loads the UI helpers with `{% load ui %}` where needed. Never add another layout, `<link>` to a CSS framework, or per-page `<style>` block. Page-specific CSS goes in `static/css/playnyu.css` under a comment naming the page.

`base.html` loads exactly this (pinned versions; bump them in one PR, never per page):

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@tabler/core@1.6.1/dist/css/tabler.min.css" integrity="sha384-tT2UAGE9hxG/p5d0iGIvZ/s8El3nWWG3tfG02i8iOY5Pbf8cZZRVmcrrVs+JG5Vw" crossorigin="anonymous">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@3.48.0/dist/tabler-icons.min.css" integrity="sha384-vLTRpuTnY1DxbKXUegP6YfVJo5azL+nO4yWUyJjWFDChoMy9oUTnSmIZhMWjI5qs" crossorigin="anonymous">
<link rel="stylesheet" href="{% static 'css/playnyu.css' %}">
...
<script src="https://cdn.jsdelivr.net/npm/@tabler/core@1.6.1/dist/js/tabler.min.js" integrity="sha384-1yCHfhyU8+V33urXkAlLLpNYd9jdzXkxdafCg0+auIIEtYFnOuM/DwJQgk5sXY98" crossorigin="anonymous"></script>
```

The `integrity` hashes make the browser refuse a CDN file that has been changed. When you bump a version, recompute the hash (`curl -s URL | openssl dgst -sha384 -binary | openssl base64 -A`).

Tabler already includes Bootstrap 5's CSS and JS. Don't load Bootstrap separately. Every Bootstrap class (`row`, `col-md-6`, `btn`, `card`, `d-flex`, ...) still works.

A page that needs a chart adds Chart.js in `{% block scripts %}`:

```html
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.min.js" integrity="sha384-jb8JQMbMoBUzgWatfe6COACi2ljcDdZQ2OxczGA3bGNeWe+6DChMTBJemed7ZnvJ" crossorigin="anonymous"></script>
```

## 3. Design tokens

Defined once as CSS variables in `static/css/playnyu.css`. Use the variable or the Tabler class, never a raw hex value in a template.

### Color

| Token | Value | Use |
|---|---|---|
| `--tblr-primary` | `#57068c` (NYU violet) | Primary buttons, links, active nav, focus rings, chart series 1 |
| `--pn-primary-hover` | `#45056f` | Hover/pressed on primary |
| `--pn-primary-tint` | `#f3ebf9` | Selected rows, "you" highlight, initials avatars (`bg-primary-lt`) |
| `--pn-series-2` | `#a78bce` | Chart series 2, the away bar (`pn-bar-away`) |
| Text | `--tblr-body-color` (Tabler default) | Body text |
| Secondary text | `text-secondary` | Meta lines, timestamps, helper text |
| Page background | `--tblr-bg-surface-secondary` (light gray) | Behind cards |
| Cards | white (`--tblr-bg-surface`) | All content surfaces |
| Success / danger / warning | Tabler `green` / `red` / `yellow` | Wins, losses, errors, warnings only. Never decoration |

Status badges use the light variants (`bg-green-lt`, `bg-red-lt`, `bg-yellow-lt`), not solid fills.

### Typography

Font: **Inter**, weights 400, 500, 600, 700 only.

| Role | Class | Size / weight |
|---|---|---|
| Page title | plain `<h1>` inside `.page-header` | 24px / 700 |
| Section / card title | `card-title` | 16px / 600 |
| Body | default | 14px / 400 |
| Secondary / meta | `small text-secondary` | 13px / 400 |
| Overline label | `subheader` | 12px / 500, uppercase (Tabler default) |
| Stat value | `h1 mb-0 pn-num` | 28px / 700 |

- Sentence case everywhere: "Create a team", not "Create A Team".
- `pn-num` (= `font-variant-numeric: tabular-nums`) on every number in a table, stat or score.
- Don't use more than two weights inside one card.

### Spacing, radius, elevation

- 4px grid. Use Bootstrap spacers (`1`=4px, `2`=8px, `3`=16px, `4`=24px, `5`=48px).
- Between page sections: `mb-4`. Inside cards: Tabler's default `card-body` padding. Don't override it.
- Radius: cards and modals **12px**, buttons and inputs **8px**, people **circle**, team logos **rounded square (10px)**. A circle always means a person and a square always means a team.
- Shadow: cards use one soft shadow (`--pn-shadow: 0 1px 2px rgba(0,0,0,.04), 0 4px 12px rgba(0,0,0,.06)`) and no border. Hover on clickable cards lifts it slightly. No other shadows.

### Icons

Tabler Icons webfont only: `<i aria-hidden="true" class="ti ti-users"></i>`. Icons next to text are decorative, so they always get `aria-hidden="true"`. Size follows the text. Icons sit beside a label, except in icon-only buttons, which need `aria-label`.

Sport icons come from the `sport_icon` filter in `core/templatetags/ui.py`. Add new sports there and here:

| Sport | Icon |
|---|---|
| Soccer | `ti-ball-football` |
| Basketball | `ti-ball-basketball` |
| American football | `ti-ball-american-football` |
| Volleyball | `ti-ball-volleyball` |
| Tennis | `ti-ball-tennis` |
| Other / unknown | `ti-trophy` |

## 4. Layout

- Top navbar (horizontal), white, with the brand left, nav center-left, and team chat, the notifications bell and the user's avatar + menu on the right.
- Content width: `container-xl`. Forms and auth pages: a single card inside `<div class="pn-auth">` (26rem wide, centered).
- Every page starts with a **page header**: optional `subheader` overline, a plain `<h1>` (no classes; a test relies on this), one `page-meta` line, and at most one primary action on the right:

  ```html
  <div class="page-header d-flex flex-wrap justify-content-between align-items-center gap-3 mb-4">
    <div class="d-flex align-items-center gap-3">
      {% include "components/team_logo.html" with team=team size="xl" %}  {# optional #}
      <div><div class="subheader">Fall 2026</div><h1>Violets</h1><div class="page-meta">Soccer · Captain Alex Lee</div></div>
    </div>
    <a class="btn btn-primary" href="...">Add a player</a>
  </div>
  ```
- Grids: cards in `row row-cards` (Tabler's equal-gutter grid). Dashboards use a 12-column grid: stats across the top, the main content in `col-lg-8`, and a side rail in `col-lg-4`.
- Mobile: everything stacks to one column. Tables scroll horizontally inside `table-responsive`. The schedule table stacks its rows instead (see "Schedule table"). No horizontal page scroll.

### Navbar

The navbar is in `templates/base.html`. It must fit on one line for a League Admin who is also a Scorekeeper.

- Top-level items for all users: Home, My teams, Free agents, Schedule, Facilities, Forum.
- Add "My matches" for a Scorekeeper. Add "Overview" and "League setup" for a League Admin.
- Do not add a top-level item for one admin page. Link the page from League setup and from the Overview quick links.
- Seasons and Placement are admin pages. They are not top-level items.
- Set `nav_section` to `"league_setup"` in the view of each admin page. This highlights "League setup".
- Give the highlighted link `aria-current="page"`.
- Keep each label on one line. Keep `text-nowrap` on the nav list and on the right-hand group.
- Use `navbar-expand-xl`. Below 1200px, the items collapse into the toggler menu.
- Give each item icon `d-xl-none`. Icons show only in the collapsed menu.
- Show the account name from 1400px (`d-none d-xxl-block`). Keep `text-truncate pn-nav-name` on it. The maximum width is 10rem.
- Do not shorten a label to make the navbar fit. Move an item into League setup.
- Check the navbar at 1280px and at 992px after each change. No label wraps. The page does not scroll sideways.

## 5. Components

Shared partials live in `templates/components/`. Use them with `{% include %}` instead of copying the markup. The markup below is what those partials contain.

### Avatar (people)

`{% include "components/avatar.html" with person=user size="md" %}`

Renders a circle with the person's initials on violet tint (`{{ person|initials }}`). A person with no name gets "P", for "PlayNYU player". The avatar never uses the email, in the initials or in the label. When profile photos land, this partial is the only place that changes: it will show the photo when there is one.

It is hidden from screen readers by default, because the person's name is almost always right next to it. When an avatar stands alone (a stacked group, an avatar-only button), pass `labelled=True` to give it a label and a hover title. The label is `{{ person|display_name }}`.

### Person names

Show a person's name with `{{ person|display_name }}` (`{% load ui %}`). It gives the full name, or "PlayNYU player" when the person has no name. In Python, use `core.names.display_name`. Never fall back to the email or the username, which is the email. This rule also applies on League Admin pages. Show an email only where the email is the point of the field, for example the roster email that team members see.

Sizes (default `sm`): `xs` 20px (inline in text), `sm` 32px (list rows, tables, stacked groups), `md` 40px (dashboard and profile lists), `lg` 48px (team grid cards), `xl` 80px (page header). Groups of avatars use `avatar-list`, max 5 then `+N`. Don't use `avatar-list-stacked` with initials: the overlap cuts the letters off. It's fine once avatars are photos.

### Team logo

`{% include "components/team_logo.html" with team=team size="md" %}`

Same as the avatar, but a rounded square instead of a circle. Until logo uploads exist it shows the team's sport icon (`{{ team.sport|sport_icon }}`) on violet tint. In the header of a team page, the logo is `xl`. Takes `labelled=True` the same way. Icons that aren't a person or team (status icons, feature tiles) may use either shape; keep each page consistent.

### Team link

`{% include "components/team_link.html" with team=team size="sm" %}`

The logo, then a `text-reset fw-medium text-break` link with the team name to its page (`teams:detail`). Use it wherever a team name appears outside its own page. In a clickable match row, `.pn-row-link` lifts the team link above the row's stretched link (see "Match rows").

Pass `link=False` when the viewer can't open the team page. The name then shows as plain text (`fw-medium text-break`). `matches/_match_teams.html` passes the flag on.

### Cards

```html
<div class="card">
  <div class="card-header">
    <h3 class="card-title">Roster</h3>
    <div class="card-actions"><span class="text-secondary small pn-num">8 / 12</span></div>
  </div>
  <div class="card-body">...</div>
</div>
```

A clickable card (a team in a grid): add `card-link card-link-pop` and a single `stretched-link`. Inside, show the logo `md`, then the name (600), then one meta line (sport · season), and optionally a stacked avatar group.

### Tabs (inside a card)

Use tabs to switch one card between parallel views of the same thing, such as one leaderboard per sport. Don't use tabs to hide unrelated content or as page navigation.

```html
<div class="card">
  <div class="card-header">
    <div><h3 class="card-title">Standings</h3><div class="small text-secondary">Fall 2026</div></div>
    <div class="card-actions"><a href="...">Full standings</a></div>
  </div>
  <div class="card-header">
    <ul class="nav nav-tabs card-header-tabs flex-nowrap overflow-x-auto overflow-y-hidden text-nowrap position-relative" role="tablist" aria-label="Standings by sport">
      <li class="nav-item" role="presentation">
        <button class="nav-link active" id="standings-tab-1" type="button" role="tab" data-bs-toggle="tab" data-bs-target="#standings-sport-1" aria-controls="standings-sport-1" aria-selected="true">
          <i aria-hidden="true" class="ti ti-star text-primary me-1"></i>Soccer<span class="visually-hidden"> (your sport)</span>
        </button>
      </li>
      <li class="nav-item" role="presentation">
        <button class="nav-link" id="standings-tab-2" type="button" role="tab" data-bs-toggle="tab" data-bs-target="#standings-sport-2" aria-controls="standings-sport-2" aria-selected="false" tabindex="-1">Basketball</button>
      </li>
    </ul>
  </div>
  <div class="tab-content">
    <div class="tab-pane active show" id="standings-sport-1" role="tabpanel" aria-labelledby="standings-tab-1" tabindex="0">...</div>
    <div class="tab-pane" id="standings-sport-2" role="tabpanel" aria-labelledby="standings-tab-2" tabindex="0">...</div>
  </div>
</div>
```

- Put the tabs in their own `card-header`, under the header with the title. Tabler fills that header with the tab strip.
- Use `<button>` tabs with `data-bs-toggle="tab"`. `tabler.min.js` switches them. Don't add JavaScript.
- Make the first tab active. Give only the active tab `aria-selected="true"`. Give the other tabs `tabindex="-1"`.
- Build ids from a primary key: `standings-tab-{{ pk }}` and `standings-sport-{{ pk }}`. Ids must be unique on the page.
- Keep the tab row on one line. `flex-nowrap overflow-x-auto overflow-y-hidden text-nowrap` scrolls it inside the card on narrow screens.
- Add `position-relative` to the tab row. Without it, `visually-hidden` text in a tab escapes the row and makes the page scroll sideways.
- Keep `overflow-y-hidden`. Without it, the active tab's 1px overlap adds a vertical scrollbar.
- Mark the user's own items with a star before the label: `ti ti-star text-primary` and `aria-hidden="true"`.
- Add the star's meaning as text for screen readers: `<span class="visually-hidden"> (your sport)</span>`.
- Put the user's own items first. Give each pane its own empty state.

### List rows (rosters, members, activity)

`list-group list-group-flush` inside a card. Each row: avatar `sm` · name (500) with secondary text below · trailing badge or action. Row height around 48px. Destructive row actions are `btn btn-sm btn-ghost-danger` and the label says what they do ("Remove"). The Report action on a forum post is `btn btn-sm btn-ghost-secondary` with `ti-flag`. A reported post shows a `badge bg-yellow-lt` "Reported" in its place.

### Match rows (schedules)

`{% include "components/match_row.html" %}` inside a `list-group list-group-flush`, with `match` in context. Match rows are for short lists: the dashboard, team, facility and profile pages, My matches and the round-robin preview. The Schedule page uses the schedule table below. Each row shows both team logos and names, with the time and facility on a secondary line. Build the query with `matches.schedule.schedule_matches()`, which selects what the row needs. The facility name links to its details only while the facility is active, because inactive ones have no public page. Cancelled matches stay in the list with a `Cancelled` badge (`bg-secondary-lt`).

Each team name links to its team page (`components/team_link.html`). The time and the final score are `text-reset` links to the match page (`matches:detail`). Don't wrap the matchup in a link, because links can't nest. `matches/_my_match_row.html` on My matches uses the same links.

The whole row opens the match page:

- Give the row `position-relative pn-row-link`.
- Make exactly one match link in the row a `stretched-link`. In a match row it is the time. Its `aria-label` is "Open match: Home vs Away, Mon Nov 16, 6:00 PM".
- Bootstrap puts the stretched link's `::after` over the whole row at `z-index: 1`. `.pn-row-link` (in `playnyu.css`) gives every other link and `.btn` in the row `position: relative; z-index: 2`. They sit above the overlay, so the team, facility, score and action links stay separately clickable.
- `.pn-row-link` adds `cursor: pointer` and a `--tblr-bg-surface-secondary` hover background.
- Never nest an `<a>`. A row with no match page to open gets no stretched link and no `pn-row-link`.

On My matches, a row in a draft season doesn't link its time or score, and gets no stretched link, because players get a 404 on that match page. It shows the team names as plain text (`link=False`), because `teams:detail` is a 404 too. League Admins still get the team links: the view sets `can_see_drafts`.

On a facility page, pass `facility_page=True`: the meta line shows the sport in place of the facility.

A row can end with one action. Pass `action_url` and `action_label`: `{% include "components/match_row.html" with action_url=url action_label="Record score" %}`. The action renders as `btn btn-sm btn-outline-secondary`.

### Schedule table

The Schedule page (`matches/schedule.html`) shows every match in one `table card-table pn-schedule`. Build the rows with `matches.schedule.schedule_matches()`, then `annotate_schedule_rows()`. That call adds `period_line` and `top_performer` in 3 queries.

- Columns: Date (date, time below), Sport (icon and name), Home, Score, Away, Venue, Top.
- The date and the score are `text-reset` links to `matches:detail`. Team names use `components/team_link.html`. Never nest a link.
- The whole row opens the match page with the "Match rows" pattern (`<tr class="pn-row-link position-relative">`). The stretched link is in the score cell: the score, "vs" before a result, or the `Cancelled` badge. It has the same `aria-label`.
- The score is centered between the teams: this is the one table number that is not right-aligned.
- Before a result, the score cell shows "vs". A cancelled match shows a `Cancelled` badge (`bg-secondary-lt`) and no score.
- Under the score, the period line: the sport's `period_label`, then "home-away" per period, then `OT1 3-2` per overtime period. Example: `Q 14-12 18-15 12-14 14-10 OT1 3-2`.
- Top: avatar `xs`, last name (or `display_name`), value and event type name. Show `—` with no stats.
- Top performer rule: the highest value of the sport's scoring event type. That type is the sport's first `EventType` by pk. A tie goes by full name.
- Sortable headers are links with `aria-sort` on the sorted `<th>`. The sorted header is bold with a chevron. A click on it reverses the direction.
- Rows of the viewer's teams get `pn-row-me`.
- Below 768px, CSS in `playnyu.css` turns each row into a stacked block: date and sport, home, away, score, venue, top. The header row becomes a wrapping row of sort links. The page never scrolls sideways.

### Stat card (dashboards)

```html
<div class="card card-sm">
  <div class="card-body">
    <div class="subheader">Wins</div>
    <div class="h1 mb-0 pn-num">7</div>
    <div class="small text-green"><i class="ti ti-trending-up"></i> +2 this week</div>
  </div>
</div>
```

Four across on desktop (`col-6 col-lg-3`). The label is always above the value, and there's at most one trend line.

A stat card that opens its list is one link: `<a class="card card-sm card-link card-link-pop h-100" href="...">` with the same `card-body` inside.

### Leaderboard / stats table

```html
<div class="card">
  <div class="table-responsive">
    <table class="table table-vcenter card-table">
      <thead><tr><th class="w-1">#</th><th>Team</th><th class="text-end">P</th><th class="text-end">W</th><th class="text-end">Pts</th></tr></thead>
      <tbody>
        <tr>
          <td class="pn-num text-secondary">1</td>
          <td><div class="d-flex align-items-center gap-2">{% include "components/team_logo.html" with team=t size="sm" %}<span class="fw-medium">Violets</span></div></td>
          <td class="text-end pn-num">6</td><td class="text-end pn-num">5</td><td class="text-end pn-num fw-bold">15</td>
        </tr>
      </tbody>
    </table>
  </div>
</div>
```

- Rank column first, muted. The column you sort by is bold.
- The current user's team or row gets `class="pn-row-me"` (violet tint). It works on table rows and on `list-group-item` rows.
- Short column headers (P, W, D, L, Pts) with a `title` attribute spelling them out.
- Form guide: small `badge` squares, `bg-green` W, `bg-secondary` D, `bg-red` L.

### Form chips

The form guide as chips: `badge pn-form-chip bg-green text-white` (W), `bg-secondary` (D), `bg-red` (L).

- Show the letter always. Color is never the only signal.
- Newest first, at most 5.
- Each chip is a link to its match (`matches:detail`).
- Give each chip a `title`: "W 3–1 vs Bobcats · Nov 2". Put the same words in a `visually-hidden` span.
- The chip for the current match is a `<span>` with `aria-current="page"` and no link.
- `.pn-form-chip` is a 1.75rem square. Below 768px it is at least 40px tall, for touch.

### Comparison bars

Two totals side by side, without Chart.js:

```html
<div class="d-flex justify-content-between"><span class="pn-num fw-bold">12</span><span class="small text-secondary">Rebounds</span><span class="pn-num">9</span></div>
<div class="progress progress-sm" aria-hidden="true">
  <div class="progress-bar bg-primary" style="width: 57%"></div>
  <div class="progress-bar pn-bar-away" style="width: 43%"></div>
</div>
```

- Home is `bg-primary` (series 1). Away is `pn-bar-away` (series 2, `--pn-series-2`).
- The bars are `aria-hidden="true"`. The numbers are the text version. The larger number is `fw-bold`.
- Leave out a row where both numbers are 0.
- A legend above the rows names each team, with a `pn-legend` swatch.

### Movement

A team's standings change across one match:

- Up: `ti-arrow-up` in `text-green`, then the number of places.
- Down: `ti-arrow-down` in `text-red`, then the number of places.
- Same: `ti-minus` in `text-secondary`, then "No change".
- A team's first result: a `badge bg-secondary-lt` "First result", and no arrow.
- The arrow is `aria-hidden`. A `visually-hidden` span says it in words: "Up 2 places, from 5th to 3rd in East" ("of the season" with no division).
- Under it: "5th → 3rd in East · 11 → 14 pts (+3)".

### Buttons

| Kind | Class | When |
|---|---|---|
| Primary | `btn btn-primary` | The single main action on the screen |
| Secondary | `btn btn-outline-secondary` | Other actions |
| Quiet | `btn btn-ghost-secondary` | Toolbars, "Cancel" |
| Destructive | `btn btn-outline-danger` (or `btn-ghost-danger` in rows) | Remove, Leave, Delete |

Labels start with a verb ("Add player", "Leave team"). An icon goes before the label. Disabled buttons explain why in a `title` or nearby text ("Roster full").

### Forms

Labels above inputs (`form-label`), inputs `form-control` / `form-select`, help text `form-hint`, errors `invalid-feedback d-block` under the field, and the submit button at the bottom left (on auth cards it is full width, `w-100`). Render a whole form with `{% include "components/form_fields.html" %}` (it adds the right classes and error states through the `control` filter). Don't use `{{ form.as_p }}`, and don't add CSS classes in Python form code.

A warning the user can override (a booking overlap, say) is an `alert alert-warning text-body` with `role="alert"` at the top of the form, not a red error. Keep `text-body`: Tabler's amber alert text is only about 2:1 on its background. Don't use `text-secondary` inside it either, because that sits right at the 4.5:1 limit. It says what's wrong and what to do, and the submit button's label changes to match ("Schedule anyway").

### Dependent selects

Use this when one select limits another, such as season, then sport and division.

- Put the controlling field first.
- Make the form work with no JavaScript. Group the dependent options in one `<optgroup>` for each parent. Validate the pair on the server.
- When the parent fixes a field's value, set that value on the server. Ignore the submitted value. A disabled field sends nothing.
- Add the script as an enhancement. Pass the rules with `json_script`, and put the code in `static/js/`. Do not write inline handlers.
- On change, the script keeps only the parent's options. It sets and disables a field that the parent fixes.
- Say the rule in the field's `form-hint`, so the form reads the same with and without the script.

The season fields use `{% include "components/season_fields.html" %}` in `{% block scripts %}`. The form needs `SeasonFieldsMixin` (`teams/forms.py`). The script is `static/js/season_fields.js`. A form with no sport field works too: the script then narrows only the divisions.

### Badges

Role and status only: `badge bg-primary-lt` (Captain), `badge bg-secondary-lt` (neutral state), plus the green/red/yellow `-lt` variants for status. Sentence case, one or two words.

A roster row for an inactive player (not signed up, or not verified) shows `badge bg-secondary-lt` "Not signed up yet" as the trailing item. This badge is the one exception to the two-word limit. Show the name as plain text, with no profile link.

Unread counts are the one number badge. Render nothing when the count is 0.

- In a list row: `<span class="badge bg-primary-lt pn-num">3<span class="visually-hidden"> unread messages</span></span>`, as the trailing item.
- In the navbar (bell, team chat): `<span class="badge bg-red-lt ms-1 pn-num">3</span>` after the icon. Put the count in the link's `aria-label` ("Team chat, 3 unread").

Season states use `{% include "components/season_state_badge.html" with season=season %}`: Draft and Closed are `bg-secondary-lt`, Open (registration) is `bg-green-lt`, Active (under way, rosters locked) is `bg-yellow-lt`.

### Empty states

```html
<div class="empty">
  <div class="empty-icon"><i class="ti ti-users"></i></div>
  <p class="empty-title">No teams yet</p>
  <p class="empty-subtitle text-secondary">Create a team or ask a captain to add you.</p>
  <div class="empty-action"><a class="btn btn-primary" href="...">Create a team</a></div>
</div>
```

Every list and table has one. Say what's missing and what to do next.

### Pagination

A long list shows 20 rows per page. Put the pager in a `card-footer` under the list, and show it only when there is more than one page:

```html
<div class="card-footer d-flex align-items-center">
  <p class="m-0 small text-secondary pn-num">Page 2 of 5</p>
  <nav class="ms-auto" aria-label="Topic pages">
    <ul class="pagination m-0">
      <li class="page-item"><a class="page-link" href="?page=1"><i aria-hidden="true" class="ti ti-chevron-left"></i>Previous</a></li>
      <li class="page-item disabled"><span class="page-link">Next<i aria-hidden="true" class="ti ti-chevron-right"></i></span></li>
    </ul>
  </nav>
</div>
```

Use Django's `Paginator`. Keep the list's filter in each page link (`?sport=3&page=2`). A link that has no target is a `<span>` inside `page-item disabled`.

Render the pager with `{% include "components/pager.html" with page_obj=page label="Free agent pages" %}`. It takes `page_obj`, `querystring` and `label`:

- `querystring` is the urlencoded filter without `page`, or empty. Build it in the view: `request.GET.copy()`, pop `page`, then `.urlencode()`.
- `label` is the `aria-label` of the `<nav>`.
- The partial renders nothing when there is only one page.

### Messages

Django messages render once in `base.html` as Tabler alerts (`alert alert-success|danger|warning|info alert-dismissible`). Pages never render their own.

### Charts (Chart.js)

Series 1 is `#57068c`, series 2 is `#a78bce`, then the neutral gray `#adb5bd`. No 3D, no pie charts with more than 4 slices, gridlines light gray, Inter 12px labels. Always put a text version of the key number next to the chart.

### Maps (Leaflet)

A page with a map puts `{% include "components/map_styles.html" %}` in `{% block head %}`, a `<div class="pn-map" id="pn-map" role="region" aria-label="...">` inside a card, and these in `{% block scripts %}`:

```html
{{ markers|json_script:"pn-map-markers" }}
{% include "components/map_assets.html" %}
```

`markers` is a list of `{name, lat, lng, url}`. `static/js/facility_map.js` draws the pins and keeps OpenStreetMap's attribution visible, which its license requires. Leaflet 1.9.4 is pinned in those two partials. Always list the same places as text next to the map, because a map alone isn't accessible.

## 6. Page recipes

| Page | Structure |
|---|---|
| **Home / dashboard** | Page header ("Hi, {first name}") → 4 stat cards: next match, record, games played, unread → `col-lg-8`: my teams, upcoming matches, standings (one tab per sport) → `col-lg-4`: matches to score (scorekeepers only), team chat, forum, recent activity, teammates. See the panel rules below. |
| **League overview (League Admin)** | Page header with "Schedule a match" → 4 linked stat cards (pending requests, needs a score, flagged content, upcoming matches). Flagged content counts the messages, topics and replies in the moderation queue → `col-lg-8`: needs a score list, upcoming matches, seasons that aren't closed → `col-lg-4`: quick links with trailing counts, seasons by state, recent changes |
| **Team** | Header: logo `xl`, name, sport · season (· division), Captain name linked to their profile → members-only actions (Team chat, Add player / Leave team) → `col-lg-8`: roster list card, player stats leaderboard card (Player, GP, one column per event type), upcoming matches → `col-lg-4`: team info card (record W–D–L · Pts, position `nth of N` plus division position), team stats card, past matches. Members-only controls stay hidden from other viewers. |
| **Schedule** | Page header: h1 "Schedule", meta line "Times are New York time.", and a "My teams" toggle link (`btn-outline-secondary`, `active` when on, `ti-square` / `ti-square-check`) on the right → filter card: GET form with Sport, Season, Division (only when the chosen season has divisions), Team (one `optgroup` per season), Venue, and a Filter button (outline). Hidden inputs keep the tab, the sort and My teams → table card: `card-header` with the tabs (Upcoming, Results, All) as a `btn-group` of `btn-sm btn-outline-secondary` links, the active one `active` with `aria-current="page"`, and the match count in `card-actions` → the schedule table → the pager (50 rows) in the `card-footer`. Upcoming sorts soonest first, Results newest first. Every link rebuilds the query from the cleaned filters, so a bad value is dropped. Draft seasons show only to League Admins, labelled "(draft)" in the Season select. Empty state: "No matches match these filters." with "Clear filters" when a filter applies, else one message for each tab. No `btn-primary`. `/matches/schedule/<pk>/` redirects to `?season=<pk>` (and keeps a valid `division`). |
| **Match** | One column, in this order at every width. Each section is a partial in `matches/templates/matches/detail/`. Page header: `subheader` season (· division), h1 "Home vs Away", meta line with time and facility (link if active), "Record score" (`btn-primary`) only for a League Admin or the assigned scorekeeper who may score it now → scoreboard card: `row text-center`, `col-4` each: home logo `xl` and name, score (`h1 mb-0 pn-num`) with a badge (Final `bg-green-lt`, Scheduled or Cancelled `bg-secondary-lt`, Awaiting score `bg-yellow-lt`), away logo `xl` and name → **Standings** card (`_movement.html`): each team's movement (see "Movement") as of this match, in its division table, else the season table; "Full standings" in `card-actions` → **Top performers** card (`_top_performers.html`): `col-md-6` per team, at most 3 leaders (scoring stat first, then by name; a 0 never leads): avatar `xs`, last name (full `display_name` in `title` and `visually-hidden`), value `pn-num fw-bold`, stat name → box score: Periods card (only with stored periods: Team, one column per period, OT only if stored, T bold), **Team comparison** card (`_comparison.html`, see "Comparison bars"), before a result the line "Stats appear after the score is in.", then `col-lg-6` per team (`_box_score.html`): players (avatar `sm`, `display_name`, profile link if active, `pn-row-me` for the viewer), one `pn-num text-end` column per event type, and a `<tfoot>` "Team totals" row in bold. Badges: "Left team" and "Did not play" (`bg-secondary-lt`). A blank stat shows `0` in `text-secondary` → team context (`_team_context.html`): `col-lg-8` "Season so far" card ("Final standings" for a closed season) with the season today per team: linked team, W–D–L · Pts, `nth of N` (· division position), last 5 as form chips; `col-lg-4` **Head-to-head** card: "Home 1 · Draws 0 · Away 0" and one row per meeting this season, or "First meeting this season." → **Venue** card (`_venue.html`): `pn-map pn-map-sm` map only for an active facility with coordinates, the name (link if active), address and borough, then "Kept score by" (final) or "Scorekeeper": avatar `xs` and `display_name`, or "Not assigned". By status: Standings, Top performers, Team comparison and totals need a counted result (not cancelled, both scores set). Season so far, Head-to-head and Venue always show. If the page gets busy, cut the comparison bars first, then the head-to-head list, then the map. Never show an email. |
| **Record the score** | `container-xl` page, not `pn-auth`. Page header (`subheader` season, h1 "Record the score", meta "Home vs Away · time") → overwrite warning (`alert alert-warning text-body`) → sheet errors (`alert-danger`) → `col-lg-4`: "Final score" card (`form_fields.html`), "Periods" card (table: Period, Home, Away; OT1 and OT2 rows blank unless stored) → `col-lg-8`: one card per team (table: Player, Played checkbox, one number input per event type; a player who left shows stored values as text with a "Left team" badge) → "Save score" (primary) and "Cancel" (ghost, to the match page). Inputs: `{{ field|control:"form-control-sm pn-num text-end pn-sheet-input" }}`, with `aria-label` "Alex Lee, Goal" / "Alex Lee played". Tables scroll in `table-responsive`. |
| **My matches (scorekeeper)** | Page header → one card per section, in this order: Needs a score, Upcoming, Scored → each card holds match rows with both team logos and its own empty state. Only the first row of Needs a score has the primary button. |
| **Generate a round-robin (League Admin)** | Page header with Back to matches (ghost) → `col-lg-4`: form card (season, division, first date, time, match length, days between rounds, facilities) → `col-lg-8`: Preview card: counts in `card-actions`, the overlap warning (`alert alert-warning text-body`), then one `subheader` and one list of match rows for each round, with an `Overlap` badge (`bg-yellow-lt`) on a row that clashes → `card-footer` with the primary action. Before a preview, the primary action is "Preview schedule". After it, the primary action is "Create N matches" ("... anyway" with overlaps) and the form button becomes "Update preview" (outline). |
| **Facility** | Page header → three stat cards (Next game, Upcoming, This semester; `col-6 col-lg-4`). The Next game value is a date, so it uses `h3` in place of `h1` to fit at phone width → `col-lg-8`: Upcoming games grouped by day (`subheader` per day, match rows with `facility_page=True`, pager), Recent results, map → `col-lg-4`: Sports with games by sport |
| **Profile** | Header: avatar `xl`, name, team count, Edit button (owner only) → `col-lg-8`: teams card (linked names, position · record or record), season stats card (one table per team, season name and `GP n`, per-game `–` with no games), recent matches card (match rows with the player's `N Stat` line) → `col-lg-4`: owner-only details card (N number, NetID). Private fields stay hidden from other viewers. |
| **Leaderboard** | Page header with a season `form-select` on the right, and a division `form-select` beside it only if the season has divisions → one full-width leaderboard table. All divisions: each team shows its division in `small text-secondary` under its name. One division: only its teams, and a `card-footer` line says that records count all season matches. |
| **Teams directory** | Page header with \"My teams\" (outline) on the right → filter card (sport, season, division only with a season, name search) → one full-width leaderboard table: Team (linked), W, D, L, Pts, Pos (`nth of N`, \"–\" with no season). Your teams get `pn-row-me`. Pagination in the `card-footer` keeps the filters. No `btn-primary`. |
| **Free agents** | Page header → Request placement and Your requests cards → full-width Free agents card: GET filter (season, sport, division), list rows (avatar `sm`, linked name, sport · division · requested date), own row `pn-row-me`, pager in `card-footer`. A captain of a team in the row's season sees a trailing Message link (`btn btn-sm btn-outline-secondary`, `ti-message`) to `{% url 'chat:new' %}?to=<user_pk>`. The viewer's own row has no link. Empty state: "No free agents yet" with no filter chosen, "No free agents match these filters." when a filter applies |
| **Forum** | Page header with the primary action (Start a topic) → sport `form-select` filter (All topics, General, each sport) → one full-width card of topic rows: author avatar `sm`, linked title, meta line (author · sport · last activity), reply count on the right → pagination in the `card-footer` |
| **Forum topic** | Page header: `subheader` "Forum · {sport}", title, Back to forum (outline), Delete topic (League Admin only, `btn-outline-danger`) → topic card: author avatar `md`, name, time, body, Report → Replies card: list rows, oldest first, with Report and Delete (League Admin only, `btn-ghost-danger`) → reply form card with the primary action (Post reply) |
| **Moderation queue** | Page header: `subheader` "League Admin", title "Flagged content" → three full-width cards (Messages, Topics, Replies), each with a count and its own empty state → list rows: author avatar `sm`, name, meta line (team or sport · linked topic · time), excerpt, Dismiss (`btn-sm btn-outline-secondary`) and Delete (`btn-sm btn-outline-danger`) |
| **Event types (League Admin)** | Page header: `subheader` "League Admin", h1 "Event types", League setup (outline) → `col-lg-7`: All event types card: list rows (sport icon avatar, name, sport below). The scoring stat row ends with a `badge bg-primary-lt` "Scoring stat" and a Clear button (`btn-sm btn-ghost-secondary`). Other rows end with "Set as scoring" (`btn-sm btn-outline-secondary`, `ti-target`). Each button is a POST form, with the type and sport in `visually-hidden` text. A `card-footer` line says what the scoring stat is → `col-lg-5`: Add an event type form card with the primary action |
| **Chat inbox** | Page header (`h1` "Chat", "Start a chat" action) → `row`: `col-lg-4 pn-chat-list` conversation list, `col-lg-8 pn-chat-thread` thread pane. The pane shows the label, one meta line, Refresh (`#latest`) and Team page (team chats) links, messages in `.pn-chat-messages` (newest last, `id="latest"`), an "Older messages" pager, and the composer (or "You can't message this person."). On a phone only one pane shows: the list hides on a conversation page, the thread hides on the inbox, and a d-lg-none "All chats" link goes back. One primary button in view: the Send action on a conversation page, the "Start a chat" action on the other inbox pages. |
| **Auth (sign up, log in, verify, claim a placeholder)** | `pn-auth` card: page header, form, full-width primary button; one secondary link below the card |

### Home / dashboard panels

`core/templates/core/dashboard.html` is the layout only. It holds the page header, the stat row, the main column and the rail.

- Make each panel one card.
- Keep the panel order from the recipe above.
- Put a panel that `core` owns in a partial: `core/templates/core/dashboard/_<panel>.html`.
- Put a panel that a different app owns in an inclusion tag in that app. Follow `notifications/templatetags/notifications_tags.py`.
- Do not add panel data to the `home` view. The inclusion tag gets its own data.
- Exception: when the stat row already loads the data, pass it to the tag as arguments. Example: `{% upcoming_matches_panel upcoming_matches past_matches %}`.
- Add the panel to `dashboard.html` with one line. Replace the `{# slot: ... #}` comment for that panel.
- Keep one blank line above and below each panel line. This prevents merge conflicts.
- Do not add a margin to a panel card. Each column sets the space with `d-flex flex-column gap-3`.
- Render nothing when a panel does not apply to the user.

## 7. Images and placeholder data

- Real uploads (profile photos, team logos) come later with S3. Until then, templates must look right with **no image**: the initials and sport-icon fallbacks above are the design, not an error state.
- Never hotlink random images. For screenshots and demos, use the fallbacks or files committed under `static/img/demo/`.
- Every `<img>` has `alt` text: the person's or team's name. Avatars that use `background-image` get `aria-label`.

## 8. Accessibility

- Text contrast is at least 4.5:1 (NYU violet on white passes; violet on `--pn-primary-tint` passes for text 14px and up).
- Every interactive element is reachable by keyboard, with Tabler's visible focus ring. Never remove `outline`.
- Touch targets are at least 40px tall on mobile.
- Don't use color alone for meaning: W/D/L badges show the letter, and errors show text.

## 9. Where things live

| What | Where |
|---|---|
| Layout, navbar, messages | `templates/base.html` |
| Tokens and the custom classes (`pn-num`, `pn-row-me`, `pn-logo`, `pn-auth`, `pn-brand-mark`, `pn-nav-name`, `page-meta`, `min-w-0`, `pn-map`, `pn-map-sm`, `pn-sheet-input`, `pn-row-link`, `pn-schedule` and its `pn-sched-*` cells, `--pn-series-2`, `pn-bar-away`, `pn-legend`, `pn-form-chip`) | `static/css/playnyu.css` |
| Match page sections (movement, top performers, comparison, box score, team context, venue) | `matches/templates/matches/detail/` |
| Shared partials (avatar, team logo, match row, form fields, map assets, season fields) | `templates/components/` |
| Template filters (`initials`: "P" with no name, never the email, `sport_icon`, `control` with optional extra classes, `display_name`: full name or "PlayNYU player", never the email, `ordinal`: 1st, 2nd, 3rd) | `core/templatetags/ui.py` |

## 10. Checklist for every UI PR (people and agents)

- [ ] Extends `base.html`. No new layout, no `<style>`, no inline `style=` except avatar/logo `background-image` and `.progress-bar` width
- [ ] No hex colors in templates. Tokens or Tabler classes only
- [ ] People have avatars (circle) and teams have logos (square), via the `components/` partials
- [ ] At most one `btn-primary` in view
- [ ] Numbers are `pn-num` and right-aligned in tables
- [ ] Every list or table has an empty state
- [ ] Looks right at 375px wide with no horizontal scroll
- [ ] Before/after screenshots in the PR description
