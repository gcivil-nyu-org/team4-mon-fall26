# Standings for every sport on the home page (#188)

## Intent

Signed-in players see this semester's standings for every sport on the dashboard. They don't need to join a team first. Their own sports come first.

## Goals

- The dashboard Standings card shows one tab per sport, with that sport's current semester default season.
- Sports of the player's teams come first, marked with a star. The other sports follow in alphabetical order.
- Each tab shows the full season leaderboard, across all divisions. The player's team row is highlighted.

## Non-goals

- No standings on the logged-out landing page. The standings pages need a login.
- No per-division tables.
- No change to the full standings pages.

## Approaches

- **Tabs in one dashboard card (picked).** Tabler tabs are already loaded, so no new JavaScript is needed.
- A stacked card per sport. With 9 sports, the page gets too long.
- A sport dropdown that reloads the page. It's slower to browse, and it adds a query parameter to the home page.

## Design

- The view gives the template `standings_label` (for example "Fall 2026") and `standings_tabs`.
- Each tab has `sport`, `season`, `is_mine` and `rows`. Each row is a `compute_standings` row with an extra `is_me` key.
- A tab exists for each sport with a visible default season where `Season.term` matches `current_semester(today).term`.
- "Mine" means the player is on a roster of a team that plays that sport.
- `teams/semesters.py` holds the semester dates. The seed command and the dashboard both use it.
- `docs/DESIGN.md` gets a Tabs component.
