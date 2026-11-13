# PlayNYU plan: E5, E6, E7, E9

Roadmap for the four remaining epics: what is already on `testing`,
what is in flight in the Nov 9–15 wave, and what is left after it.
Deploy order for everything below is `testing` first, then `main`
(see [WORKFLOW.md](WORKFLOW.md)): feature branch → PR into `testing`
(review, green Travis build, check on the testing site) → PR from
`testing` into `main` (review, green build, merge).

## What exists on `testing`

The E2 league-configuration base is merged and deployed to the testing
site:

- Season lifecycle: Draft → Open → Active → Closed, with guarded
  transitions, per-state action rules, divisions, and the sports /
  event-type catalogs.
- Teams and rosters: team creation in open seasons, roster capacity,
  one team per player per season, captain / player roles.
- Free agents: player requests plus the League Admin matching flow.
- Scheduling: season and team schedule pages, overlap warnings for
  double-booked facilities, scorekeeper assignment.
- Facilities: 154 NYC Parks facilities near NYU plus 8 NYU / Hudson
  River Park venues seeded from `facilities/data/`, with the map and
  the manage pages.
- Accounts with the League Admin, Scorekeeper and Casual Player roles,
  the signed-in home dashboard, persistent Postgres on the deployed
  sites (`DATABASE_URL`), and the Travis CI + coverage gate.

## In flight: Nov 9–15 wave

- **E5 – Results and standings** (`shaahid/e5-results`): entering match
  results and computing standings / leaderboards on top of the
  scheduling base.
- **E6 – Notifications** (`shaahid/e6-notifications`): notifying
  players about the matches and teams that involve them.
- **E7 – Team chat** (`shaahid/e7-team-chat`): team-scoped chat.
  Direct messages, comments and blocking are explicitly out of scope
  for this wave (see Icebox below).
- **E9 – Secure and observe**: the audit log for admin actions lands
  in this wave.
- **League Admin overview (#154)**: the `core` overview page in this
  PR — league-wide stat cards (seasons by state, teams, pending
  free-agent requests, upcoming matches, active facilities), upcoming
  matches, and quick links to every admin page.

## What remains

- **Icebox**: DMs, comments and blocking stay in the Icebox — no
  near-term plan, revisit after team chat lands.
- **E9 leftovers**: create the error-tracking account and run the
  backup-restore test against the deployed database.
- **Epic-text updates**: update the E5/E6/E7/E9 epic issue bodies to
  match this plan (scope, in-flight cards, icebox items).

## Card tracker

| Card | Work | State |
|---|---|---|
| #9 | Verify `facilities/data/nyu_venues.csv` against real NYU venues | Done in this PR (Chelsea Waterside sports fixed) |
| #150 | Write this roadmap | Done in this PR |
| #154 | League Admin overview page in `core` | Done in this PR |
