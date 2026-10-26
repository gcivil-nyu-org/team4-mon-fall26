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

- Top navbar (horizontal), white, with the brand left, nav center-left, and the user's avatar + menu on the right.
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
- Mobile: everything stacks to one column. Tables scroll horizontally inside `table-responsive`. No horizontal page scroll.

## 5. Components

Shared partials live in `templates/components/`. Use them with `{% include %}` instead of copying the markup. The markup below is what those partials contain.

### Avatar (people)

`{% include "components/avatar.html" with person=user size="md" %}`

Renders a circle with the person's initials on violet tint (`{{ person|initials }}` falls back to the first letter of the email). When profile photos land, this partial is the only place that changes: it will show the photo when there is one.

It is hidden from screen readers by default, because the person's name is almost always right next to it. When an avatar stands alone (a stacked group, an avatar-only button), pass `labelled=True` to give it a label and a hover title.

Sizes (default `sm`): `xs` 20px (inline in text), `sm` 32px (list rows, tables, stacked groups), `md` 40px (dashboard and profile lists), `lg` 48px (team grid cards), `xl` 80px (page header). Groups of avatars use `avatar-list`, max 5 then `+N`. Don't use `avatar-list-stacked` with initials: the overlap cuts the letters off. It's fine once avatars are photos.

### Team logo

`{% include "components/team_logo.html" with team=team size="md" %}`

Same as the avatar, but a rounded square instead of a circle. Until logo uploads exist it shows the team's sport icon (`{{ team.sport|sport_icon }}`) on violet tint. In the header of a team page, the logo is `xl`. Takes `labelled=True` the same way. Icons that aren't a person or team (status icons, feature tiles) may use either shape; keep each page consistent.

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

### List rows (rosters, members, activity)

`list-group list-group-flush` inside a card. Each row: avatar `sm` · name (500) with secondary text below · trailing badge or action. Row height around 48px. Destructive row actions are `btn btn-sm btn-ghost-danger` and the label says what they do ("Remove").

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

### Badges

Role and status only: `badge bg-primary-lt` (Captain), `badge bg-secondary-lt` (neutral state), plus the green/red/yellow `-lt` variants for status. Sentence case, one or two words.

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

### Messages

Django messages render once in `base.html` as Tabler alerts (`alert alert-success|danger|warning|info alert-dismissible`). Pages never render their own.

### Charts (Chart.js)

Series 1 is `#57068c`, series 2 is `#a78bce`, then the neutral gray `#adb5bd`. No 3D, no pie charts with more than 4 slices, gridlines light gray, Inter 12px labels. Always put a text version of the key number next to the chart.

## 6. Page recipes

| Page | Structure |
|---|---|
| **Home / dashboard** | Page header ("Hi, {first name}") → 4 stat cards → `col-lg-8`: my teams card grid, upcoming games list → `col-lg-4`: leaderboard snippet (top 5), free agents avatar group |
| **Team** | Header: logo `xl`, name, sport · season, primary action (Add player / Leave team) → `col-lg-8`: roster list card → `col-lg-4`: team stats card, recent results |
| **Profile** | Header: avatar `xl`, name, NetID (owner only), Edit button (owner only) → teams card grid → stats card |
| **Leaderboard** | Page header with a season `form-select` on the right → one full-width leaderboard table |
| **Auth (sign up, log in, verify)** | `pn-auth` card: page header, form, full-width primary button; one secondary link below the card |

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
| Tokens and the custom classes (`pn-num`, `pn-row-me`, `pn-logo`, `pn-auth`, `pn-brand-mark`, `page-meta`, `min-w-0`) | `static/css/playnyu.css` |
| Shared partials (avatar, team logo, form fields) | `templates/components/` |
| Template filters (`initials`, `sport_icon`, `control`) | `core/templatetags/ui.py` |

## 10. Checklist for every UI PR (people and agents)

- [ ] Extends `base.html`. No new layout, no `<style>`, no inline `style=` except avatar/logo `background-image` and `.progress-bar` width
- [ ] No hex colors in templates. Tokens or Tabler classes only
- [ ] People have avatars (circle) and teams have logos (square), via the `components/` partials
- [ ] At most one `btn-primary` in view
- [ ] Numbers are `pn-num` and right-aligned in tables
- [ ] Every list or table has an empty state
- [ ] Looks right at 375px wide with no horizontal scroll
- [ ] Before/after screenshots in the PR description
