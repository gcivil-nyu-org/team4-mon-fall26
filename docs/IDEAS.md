# Ideas backlog: gamification, social, stats, formats, campus events

Status: backlog only. None of these ideas is planned or scheduled. Before you build one, open an issue and write a design spec. Written 2026-11-16 (#258).

## 0. Sources and caveats

- **App facts** come from `origin/testing` (fetched 2026-11-16): `README.md`, `docs/PLAN.md`, `docs/DESIGN.md`, `teams/models.py`, `teams/event_types.py`, `teams/management/commands/seed_league_data.py`, `matches/models.py`, `matches/standings.py`, and the chat, forums, notifications, facilities, audit, profiles and accounts models. The local working tree is behind `origin/testing` (it has no `EventType.is_scoring`). Some files were read from the working tree because the shell was unreliable: `matches/standings.py`, `profiles/models.py`, `accounts/models.py` and `docs/DESIGN.md`. They may differ slightly from `testing`.
- **Web research did not run.** WebSearch failed every time (the tool safety check gave no verdict). The notes on comparable products come from what I already knew (to mid-2026). Check them before you quote them in a pitch.

## 1. What the app has today (the parts these ideas use)

| Area | Models and facts |
|---|---|
| League | `Sport` (`period_count`, `period_label`), `EventType` (`sport`, `name`, `is_scoring`), `Season` (Draft → Open → Active → Closed, `term`, `max_roster_size`, `registration_closes_on`), `Division`, `Team` (`captain`, `season`, `division`), `Roster` (`role` captain/player, `joined_at`), `FreeAgentRequest` |
| Seeded sports | Basketball, Cricket, Flag football, Futsal, Pickleball, Soccer, Softball, Ultimate frisbee, Volleyball |
| Default event types | Basketball: Points (scoring), Assists, Rebounds. Futsal: Goals (scoring), Assists, Yellow cards. Volleyball: Kills, Aces (no scoring stat; the final score is sets won) |
| Matches | `Match` (home/away team, **facility is required** with PROTECT, `starts_at`/`ends_at`, `status` scheduled/cancelled, `home_score`/`away_score`, `scorekeeper`, `created_by`), `MatchPeriodScore` (periods past `period_count` are OT1/OT2), `PlayerStat` (match, player, **team stored**, event_type, value; zero is not stored), `MatchAppearance` (match, player, team) |
| Standings | Computed, never stored: win = 3, draw = 1, sort by points, then wins, then name. `team_records()` gives all-time W-D-L. Draws are legal. |
| Social | `Conversation` (team/direct/group), `ConversationMember`, `ConversationRead`, `Block`, `Message` (500 chars, `is_flagged`), forum `Topic`/`Reply` (`is_flagged`, moderation queue), `Notification` (recipient, verb, link, is_read) |
| Other | `Facility` (city/NYU source, lat/lng, `sports` M2M, `is_active`), `AuditLog` (admin changes), `PlayerProfile` (`n_number`, `net_id` only), `PendingAccount` (placeholder players added by email before sign-up) |
| Roles | League Admin, Scorekeeper, Casual Player |
| UI rules that matter here | Tabler + Django templates, no JS framework, Chart.js allowed on chart pages. Faces and crests first. One violet primary button. Numbers use `pn-num`, right-aligned. `pn-row-me` for the viewer's row. Badges (the CSS kind) are for **role and status only**. No image uploads until S3, so the initials and sport icons are the design. Never show an email. |

Constraints for every idea: a small student team, weekly sprints (Monday to Monday), Elastic Beanstalk with Postgres, no websockets or Celery today. Anything "live" means a page refresh or a management command run by cron (the same pattern as `advance_season_states`).

**A naming clash to fix first:** DESIGN.md uses "badge" for the Tabler CSS chip. Call achievements **"awards"** in code (`Award`, `PlayerAward`) and in DESIGN.md, or add an "Achievement chip" component to DESIGN.md. This doc says "badge" for readability.

## 2. Comparable products: patterns worth copying (from memory)

| Product | Pattern | Use for PlayNYU |
|---|---|---|
| IMLeagues (campus intramurals) | Sportsmanship ratings from officials after each game, with a minimum average to reach playoffs. Season to playoff brackets. Free-agent boards. Team "championship" shirts. | Sportsmanship rating from the scorekeeper. A playoff bracket from the standings. A champion trophy. |
| Playpass / Playpass-like rec apps | Pickup sessions and drop-in events with a capacity, a waitlist and RSVP. One-day tournaments. | `Event` + `EventRSVP` for pickup and open gym. |
| TeamSnap | Per-match availability (Yes / No / Maybe), a reminder before the game, a captain's view of who is coming. Team announcements. | `MatchAvailability` on match and team pages. |
| LeagueApps | Registration, payments, league to playoffs in one admin flow. | Playoffs as a season stage, not a separate product. |
| Strava | Kudos (one tap, no text), segment leaderboards, monthly challenges with a badge for finishing, privacy zones, follower-only activities. | Kudos on a match. Fitness challenges. Privacy defaults. |
| Chess.com / lichess | Elo/Glicko rating, a provisional rating until N games, a rating graph, achievements. | Ladders for solo sports and chess. A provisional mark. |
| FPL (Fantasy Premier League) | Weekly cycle ("gameweek"), mini-leagues among friends, "dream team" of the week. | Pick'em by week. "Team of the week". |
| Discord | Roles, channels, reactions, pinned messages, events with RSVP. | Pinned captain announcements in team chat. Emoji reactions (a short fixed set). |
| start.gg / Challonge | Single and double elimination, Swiss, round robin pools then a bracket, best-of-N series, seeding, check-in, self-reported scores confirmed by the opponent. | Tournament stages, seeding from standings, best-of series for esports, check-in. |

## 3. Ideas by area

Effort: **S** = 1–2 days, **M** = one weekly sprint, **L** = several sprints. "Reuses" lists existing models. "New" lists new models or fields.

### 3.1 Leaderboards and gamification

**L1. Player leaderboards per stat** — A page per sport with one table per event type (Points, Goals, Assists, Kills...), season or all-time, with a per-game column.
- Why: players want to see their name ranked; captains scout free agents. It is the most-asked feature in every rec league app.
- Fit: reuses `PlayerStat`, `MatchAppearance` (games played), `EventType`, `Season`, `Sport`. Only matches with a result and not cancelled count (same rule as `counted_matches()`). **New:** nothing. Optional `PlayerProfile.show_on_leaderboards` (default True).
- Effort: **M** (S for one season view; M with all-time, per-game, a minimum-games filter, and tabs per stat).
- Risks: fairness — per-game numbers need a minimum games played (for example 3) or one big game tops the table. Privacy — placeholder players (`PendingAccount`) must show as plain text with no link; players need an opt-out. Gaming — a scorekeeper or a League Admin enters stats, so the risk is low; the audit log covers admin changes.

**L2. Single-match records and "Top performer"** — Each match page shows a top performer (highest scoring stat, tiebreak on other stats). A records page lists the season and all-time single-match highs ("Most points in a game: 34").
- Why: a quick, fair shout-out after every game with no voting to moderate.
- Fit: reuses `PlayerStat`, `EventType.is_scoring` through `scoring_event_type()`. **New:** nothing (computed). For volleyball (no scoring stat) use Kills + Aces.
- Effort: **S**.
- Risks: it favours scorers over defenders. Label it "Top scorer", not "MVP".

**L3. Badges / achievements (stored awards)** — A management command (cron, like `advance_season_states`) checks fixed rules and gives awards. They show on the profile and as a notification.
- Why: rewards the steady player, not only the top scorer. It brings people back each week.
- Fit: reuses `PlayerStat`, `MatchAppearance`, `MatchPeriodScore`, `Match`, `Roster`, `Team`, `Season`, `Notification`. **New:** `Award` (catalog) and `PlayerAward` (earned row). See section 7.
- Effort: **M** for a catalog of about 12 rules and the profile section.
- Risks: a score correction can take an award away. Decide whether to keep it or revoke it (recommended: revoke when the command re-runs, and send no notification for a revoke). Don't add awards for chat or forum volume (spam). Fairness: futsal has more event types than volleyball, so give each sport its own awards.

Concrete badges and their exact unlock rules (only data that exists today):

| Badge | Sport | Exact rule |
|---|---|---|
| First of many | any with a scoring stat | The player's first `PlayerStat` with `event_type.is_scoring` and `value >= 1` |
| Hat trick | Futsal, Soccer | One `PlayerStat` with event type "Goals" and `value >= 3` |
| Double-double | Basketball | In one match: Points ≥ 10 and (Rebounds ≥ 10 or Assists ≥ 10) |
| Triple-double | Basketball | In one match: Points, Rebounds and Assists each ≥ 10 |
| Playmaker | Futsal, Basketball | Assists ≥ 3 (futsal) or ≥ 8 (basketball) in one match |
| Ace machine | Volleyball | Aces ≥ 5 in one match |
| Iron player | any | A `MatchAppearance` in every counted match of the player's team in one season, with at least 5 counted matches, given when the season is Closed |
| Ever-present | any | Appearances in 10 counted matches in a row for the same team (ordered by `starts_at`) |
| Comeback | any with periods | The player's team trailed on the cumulative `MatchPeriodScore` after the second-to-last regular period, and the team won |
| Overtime hero | any with periods | The match has a `MatchPeriodScore` with `period > sport.period_count`, the player appeared, and the team won |
| Brick wall (team, given to each player who appeared) | Futsal, Soccer | The opponent's final score is 0 |
| Unbeaten | any | The team ends a Closed season with `lost == 0` and `played >= 5` |
| Champion | any | The team is 1st in `compute_standings()` when the season is Closed (later: wins the playoff final) |
| Clean game | Futsal | 6 or more appearances in one season with no "Yellow cards" stat row |
| Multi-sport | any | Appearances for teams of 3 different sports |
| Veteran | any | Appearances in 3 different seasons with a `term` |
| Captain's armband | any | `Roster.role == captain` on a team with 5 or more counted matches |
| Reliable scorekeeper (staff) | — | 10 matches scored by this scorekeeper. **Needs a new `Match.scored_at` field** to add "within 24 hours of `ends_at`" |

**L4. XP, levels and progress** — Points for appearances, wins and awards, shown as a level ("Level 4 · 320 XP").
- Why: a sense of progress for players who never top a leaderboard.
- Fit: computed from `MatchAppearance`, wins and `PlayerAward`. **New:** nothing if computed; or a cached `PlayerProfile.xp`.
- Effort: **S** once awards exist.
- Risks: XP for activity (chat, forum posts, RSVPs) invites spam. Count only things a scorekeeper confirms. Keep levels on the owner's profile, not on a public ranking. **Low value. Park it.**

**L5. MVP** — four levels:
- **Per match:** a vote by the players who have a `MatchAppearance` in that match. No self-votes. The window is 48 hours after `ends_at`. A tie goes to the higher scoring stat. With fewer than 3 votes, the auto top performer (L2) is shown in its place.
  - Why: it rewards defence, effort and leadership, which stats miss.
  - **New:** `MVPVote(match, voter, nominee, created_at)`, unique on `(match, voter)`.
  - Effort: **M**.
  - Risks: teams vote as a block for their own player. Fix: each voter votes only for a player on the **opposing** team ("best opponent"), as IMLeagues-style sportsmanship systems do, or weight the votes from both teams equally. Show only the winner, never the vote counts.
- **Player of the week:** auto. The top value of a per-sport z-score (stat compared to that sport's average per game) among matches from Monday to Sunday, to match the sprint calendar. A League Admin can override it.
  - **New:** `WeeklyAward(sport, week_start, player, match, chosen_by)`. Effort: **S–M**.
- **Per season:** "Season MVP" is the most match MVPs; "Golden boot" and the other stat awards are the leaderboard leaders with a minimum number of games. Effort: **S** after L1 and L5.
- **Scorekeeper pick:** the scorekeeper can mark one "Scorekeeper's pick" on the score sheet. It is cheap (one nullable FK on `Match`), but one person decides alone. Use it only as the tiebreak.

**L6. Streaks** — Team win streaks and player appearance or scoring streaks ("Scored in 4 straight"), shown on team and profile pages. Fit: computed from `Match` and `PlayerStat` by `starts_at`. **S.** Risk: none worth naming.

**L7. Season awards page and team trophies** — When a season closes: Champion, Runner-up, Golden boot, top assists, Iron player, Season MVP, Best sportsmanship. Champion teams get a trophy on the team and player pages.
- Fit: reuses standings and L1. **New:** `SeasonAward(season, kind, team | player, value)` frozen at close, so later score edits don't change history. **S–M.**
- Risk: freeze at Closed. A Closed season can't change matches today (`can_change`), so this is safe.

**L8. Sportsmanship rating** — After each match the scorekeeper rates each team 1–5, with an optional note visible only to League Admins. Teams below an average of 3 can be kept out of the playoffs (IMLeagues does this).
- Fit: **New:** `SportsmanshipRating(match, team, rating, note, rated_by)`. **S.**
- Risk: one scorekeeper's bias. Show only the season average, never a single rating, and let a League Admin edit.

### 3.2 Social features

**S1. Follows** — Follow a team or a player and get their results in your notifications and on a home feed.
- Why: friends and fans on other teams see results.
- Fit: **New:** `Follow(follower, team | player)`. Reuses `Notification`. **M.**
- Risks: following a person is a stalking risk on a campus app. **Allow follows of teams only**, or of players who opt in. Respect `Block`.

**S2. Reactions and comments on matches** — A fixed set of reactions (🔥 👏 💪, or Tabler icons in place of emoji) and short comments on the match page.
- Fit: **New:** `MatchReaction(match, user, kind)` unique on `(match, user, kind)`. For comments: `MatchComment(match, author, body, is_flagged)`, which goes into the moderation queue like forum replies. **Reactions S, comments M.**
- Risks: PLAN.md puts match comments in the Icebox. Reactions carry no text, so they are a safe first step. Comments need the moderation queue and Report; opponents trash-talk.

**S3. Match recap feed** — A home panel and page: "Violets beat Bobcats 3–2 · Top scorer Alex Lee (2 goals) · 3 kudos". Auto-made from the result.
- Fit: computed from `Match`, `PlayerStat`, reactions. A home panel (inclusion tag, per DESIGN.md). **S.**
- Risk: none if it shows only the teams the viewer can see (`seasons_visible_to`).

**S4. Kudos to teammates** — After a match, each player who appeared gives one kudos to one teammate, with an optional tag ("Great defence", "Hustle", "Leadership"). Totals show on the profile.
- Fit: **New:** `Kudos(match, giver, receiver, tag)` unique on `(match, giver)`. **S–M.**
- Risk: friends trade kudos. Limit one per match per giver, show only totals, and require that both people appeared in the match.

**S5. Polls** — Captains post a poll in team chat ("Practice Thursday or Friday?").
- Fit: **New:** `Poll(conversation, question, closes_at)`, `PollOption`, `PollVote`. **M.** Risk: low. **Value is low next to availability (S7). Park it.**

**S6. Captain announcements** — A captain pins one message in team chat. It shows at the top of the thread and on the team page, and sends a notification.
- Fit: **New:** `Conversation.pinned_message` (FK to `Message`, null) or `Message.is_announcement`. Reuses `Notification`. **S.**
- Risk: low. Only the captain (`Roster.role`) can pin.

**S7. Attendance / RSVP per match** — Each roster player answers Yes / No / Maybe for each upcoming match. The captain sees the count ("7 of 9 going") and who has not answered. A cron sends a reminder 24 hours before.
- Why: no-shows are the top problem in rec leagues (forfeits). TeamSnap is built around this.
- Fit: **New:** `MatchAvailability(match, player, team, status, updated_at)`. Reuses `Roster`, `Notification`. Can pre-tick "Played" on the score sheet. **M.**
- Risks: show answers only to teammates and the League Admin, never to opponents. Don't shame "No" answers.

**S8. Availability (recurring)** — The player sets weekly time slots. The round-robin generator avoids slots with low availability.
- Fit: **New:** `WeeklyAvailability(player, weekday, start, end)`. Changes `matches/round_robin.py`. **L.** Risk: scheduling becomes hard to explain. **Park it.**

**S9. Photos** — Match and team photos.
- Fit: needs S3 (not done) and image moderation. **L.** Risks: photos of people who did not agree, NSFW content, storage cost. **Avoid it until S3 exists and there is a report flow.**

**S10. Share cards** — A share image for a result or an award ("Hat trick! Alex Lee · Violets 5–2 Bobcats").
- Fit: a server-made image needs Pillow and fonts on EB. A cheaper first step is an HTML page with Open Graph tags plus a "Copy link" button. **S (OG page) / M (image).**
- Risk: a public page leaks the names of students who did not opt in. Share cards show team names only, unless the player turns on sharing.

### 3.3 Stats features

**T1. Team form and trends** — A form guide (last 5: W D L squares, as DESIGN.md already describes), goals for and against, and a points-by-week chart (Chart.js) on the team page. **S.** Reuses `Match`. No risk.

**T2. Head-to-head history** — On the match page: past results between the two teams, and the record across seasons for teams with the same name. **S.** Note: a `Team` belongs to one season, so a team across seasons is not linked. Optional **new** `Team.continues` (FK to `Team`, null) links a team to its previous season's team. Risk: none.

**T3. Player comparison** — Pick two players of the same sport and see per-game stats side by side. **S–M.** Reuses L1 queries. Risk: low; respect the leaderboard opt-out.

**T4. Team Elo / power rankings** — An Elo rating per team per sport, updated by each result. Start at 1500, K = 32, a draw counts as 0.5. A team carries its rating into the next season through `Team.continues`, or starts again each season.
- Why: it ranks across divisions and gives seeding for playoffs. It makes "upset" awards possible ("Giant killer: beat a team rated 150+ higher").
- Fit: compute it on the fly from ordered matches (small data), or cache `TeamRating(team, rating, matches_counted)`. **S–M.**
- Risks: a team with few games has a noisy rating. Show "Provisional" under 5 games (Chess.com does this). **Don't make a per-player Elo for team sports:** one player's effect can't be separated from the team's.

**T5. Predictions** — "Violets 64% to win", from Elo. **S** after T4. Risk: it can feel discouraging to a low team. Show it only on upcoming match pages, not on the team page.

**T6. Pick'em** — Players pick winners of next week's matches. A season leaderboard of correct picks.
- Fit: **New:** `Pick(match, user, picked_team)`, locked at `starts_at`. **M.**
- Risks: **never with prizes or money** (gambling rules and NYU policy). Players could throw a match to win a pick: don't allow picks on your own team's matches, or count only picks for your own team. Lower value than the rest; park it until the app has more users.

### 3.4 New formats

**F1. Playoffs after a season** — The League Admin picks "Top N to playoffs" (4 or 8). The app seeds a single-elimination bracket from `compute_standings()` (1 vs 8, 2 vs 7...), creates the matches, and makes the next round from the winners.
- Why: every intramural season ends in playoffs. This gives a real "Champion".
- Fit: reuses `Season`, `Match`, standings, facilities, scorekeepers. **New:** `Stage` (kind league/knockout, order), `Match.stage`, `Match.round`, `Match.bracket_slot`, and a way to break a draw (`Match.winner` or `decided_by` = regulation/OT/penalties/forfeit). See section 7. **M–L** (M for single elimination only).
- Risks: knockout matches can't end in a draw, but today's scoring accepts draws. The score form must ask for a winner when scores are equal. Fairness: say the tiebreak rule (points, then wins, then head-to-head) before the season, not after.

**F2. Tournaments (more formats)** — Double elimination, Swiss, pools then a bracket, round robin pools.
- Fit: the same `Stage` model with more `kind` values, plus a `Pool` (like `Division` but per stage). Swiss needs pairing logic (no repeat opponents, near-equal scores). **L** for all formats. Build single elimination first; pools to playoffs comes second (round robin already exists); double elimination and Swiss come last.
- Risk: bracket UIs without JS are hard. Use one column per round in a `table-responsive` card, or a list of rounds (as the round-robin preview does).

**F3. One-day events** — A tournament on one Saturday at one facility: pools in the morning, a bracket in the afternoon, short matches (20 minutes).
- Fit: a `Season` with the same start and end date, plus F1/F2 stages. Facility overlap checks already exist. **M** after F1.
- Risk: check-in and no-shows. Add a check-in step (start.gg pattern).

**F4. Esports leagues** — Game titles (Valorant, Rocket League, League of Legends, Smash, FIFA/EA FC), best-of series, online matches, gamer tags.
- Fit:
  - A game title is a `Sport`. Games ("maps") inside a series can reuse `MatchPeriodScore` with `period_label = "Game"` and `period_count = 3` (best of 3). The series score is games won, like volleyball sets.
  - **Facility is required today** (PROTECT, not null). Either make `Match.facility` nullable with an `is_online` flag, or seed one "Online" facility with `source = nyu`, no location and hidden from the map. Making the field nullable touches the overlap checks, the facility pages and `match_row.html`, so the "Online" facility is the cheap path (S), and the nullable field is the clean path (M).
  - **New:** `PlayerProfile.gamer_tags` or `GamerTag(user, platform, tag)`. Optional `Sport.kind` (physical/esport) so the facility map hides esports.
  - Self-reported results, confirmed by the other captain (Challonge/start.gg pattern), in place of a scorekeeper. **New:** `ResultReport(match, reported_by, home_score, away_score, confirmed_by)`.
- Effort: **M** for "esports as a sport with an online facility"; **L** with self-reporting and best-of rules.
- Risks: gamer tags link to accounts outside NYU (privacy; make them visible to teammates only by default). Game rating rules (some titles are rated M). Cheating and smurfs can't be checked. Don't integrate game APIs (Riot, Valve): the terms, keys and rate limits cost too much for a student team.

**F5. Chess** — Chess is a solo game: one player against one player, a result of 1, ½ or 0, and a rating.
- Fit: **does not fit** the `Team` model well. Option A: a one-player `Team` per entrant (a hack that keeps the schedule, standings and pages; `max_roster_size = 1`). Option B: the ladder model in F6. Use B. Link games to lichess or chess.com by URL; don't build a chess board. **M** with F6.
- Risk: online cheating; play over the board at a club meeting, or accept it as a casual league.

**F6. Solo sports and challenge ladders** — Tennis, table tennis, pickleball singles, squash, chess. Players hold a rank; a player can challenge anyone up to 3 places above; the winner takes the higher place. Or an Elo/Glicko ladder.
- Why: many students don't have a full team. Pickleball is already a seeded sport.
- Fit: **New:** `Ladder(sport, season, rules)`, `LadderEntry(ladder, player, rank, rating)`, `Challenge(ladder, challenger, challenged, status, deadline, match)`, and a solo result model (`SoloMatch(player_a, player_b, score_a, score_b, facility, reported_by, confirmed_by)`), or generalise `Match` with a nullable player pair. Reuses `Facility`, `Notification`, `Sport`. **L.**
- Risks: players dodge challenges (rule: a challenge not played within 7 days is a forfeit). Rating inflation from friends playing each other again and again (limit repeat games per week). Self-reported scores need confirmation from the opponent.

### 3.5 Other university events and activities

**E1. Pickup games / open gym / drop-in** — A session at a facility and time with a capacity, RSVP and a waitlist. Anyone verified can join; no team needed.
- Why: the lowest-commitment way into the app. Playpass is built on this.
- Fit: **New:** `Event(kind pickup/open_gym/class/fair/social, sport null, facility, starts_at, ends_at, capacity, host, is_public)` and `EventRSVP(event, user, status going/waitlist/cancelled, created_at)`. Reuses `Facility` (and its schedule page), `Notification`, the facility overlap query. **M.**
- Risks: a player-hosted session at a city park is not an NYU event (liability). Let only League Admins (or a new "Event host" role) create events at first. Waitlist fairness: first come, first served, with an auto-promote notification.

**E2. Club sports** — Club teams (not intramural) list practice times, tryouts and contacts.
- Fit: an `Event` series plus an "organisation" page. **New:** `Club(name, sport, contact_url)`. **M.** Risk: the data goes stale; club leaders must own it. Lower value; the clubs already use their own tools.

**E3. Fitness challenges and run clubs** — "Run 50 km in November", "10 open-gym visits". Players log entries; a progress bar and an award for finishing.
- Fit: **New:** `Challenge(name, metric, target, starts_on, ends_on)`, `ChallengeEntry(challenge, user, amount, date, note)`. Reuses awards. Run club meet-ups are `Event`s. **M.**
- Risks: logs are self-reported and easy to fake. Use them for completion awards only, not a ranked prize. Don't store GPS tracks (location privacy; the Strava heat map leaks are the classic warning).

**E4. Intramural fair** — A one-day page for the fair: the sports on offer, season sign-up dates, a free-agent sign-up form, a QR code to the app.
- Fit: a static page plus `Season.registration_closes_on` and `FreeAgentRequest`. **S.** Risk: none. Good value for sign-ups at the start of a term.

**E5. Campus rec classes** — Yoga, spin, and similar classes with RSVP.
- Fit: `Event(kind=class)` with E1. **S** after E1. Risk: it duplicates NYU's own booking system. Link out to it in place of RSVP when NYU already handles booking.

**E6. RSVP events (socials, watch parties, banquets)** — The end-of-season awards night with RSVP. Fit: `Event` + `EventRSVP`. **S** after E1.

**E7. Volunteer refs** — Players sign up to referee or keep score for a match they are not in. They get the Scorekeeper role for that match only, and a "Volunteer ref" award after 5 matches.
- Why: scorekeepers are the bottleneck for stats; every stats feature depends on them.
- Fit: reuses `Match.scorekeeper` and the Scorekeeper role. **New:** `RefSignup(match, user, status)`, and a per-match permission in place of the global role (the current rule needs the role: `users_with_role(SCOREKEEPER_ROLE)`). **M.**
- Risks: conflict of interest (a ref from a rival team in the same division). Block refs who play in the same division. The League Admin approves each signup.

## 4. Top 10 (value against effort, for this team)

| # | Idea | Effort | Why this rank |
|---|---|---|---|
| 1 | **L1 Player leaderboards per stat** (season and all-time, per game with a minimum) | M | All data exists. No new model. The most visible win. The leaderboard table recipe already exists in DESIGN.md. |
| 2 | **L3 Badges v1** (about 12 rule-based awards, profile section, notification) | M | Two small models and a cron command. Uses only stored stats, so it can't be gamed by players. Makes the profile page worth a visit. |
| 3 | **F1 Playoffs after a season** (single elimination seeded from standings) | M–L | Every intramural season ends in playoffs. It creates the "Champion" moment and is the base for all tournament formats. |
| 4 | **L2 Top performer and records** | S | A half-day of queries on the match page and one records page. |
| 5 | **T1 + T2 Form guide and head-to-head** | S | Pure reads from `Match`. The form guide is already designed in DESIGN.md. |
| 6 | **S7 Match RSVP / availability** | M | Fixes forfeits, the real problem in rec leagues. Captains will use it every week. Pre-fills "Played" on the score sheet. |
| 7 | **L7 Season awards and team trophies** | S–M | Cheap after #1; freezes history when a season closes. |
| 8 | **L5 Match MVP vote** (opponents vote; fallback to top performer) | M | Rewards non-stat play. Needs anti-bias rules, so it comes after the stat-based items. |
| 9 | **S2 Reactions + S4 Kudos** (no free text) | S–M | Social without a moderation burden, because there is no text. |
| 10 | **T4 Team Elo power rankings** (provisional under 5 games) | S–M | Ranks across divisions, seeds playoffs, and unlocks the "Giant killer" award and predictions. |

Next in line: S6 captain announcements (S), E1 pickup games and open gym (M), L8 sportsmanship rating (S), F4 esports through an "Online" facility (M).

## 5. Three themed sprints

Each sprint is one week (Monday to Monday, closes Sunday night). Each assumes 3–4 people.

**Sprint A: "Leaderboards and records" (Gamification v1)**
1. Player leaderboard page: one tab per event type, season `form-select`, all-time toggle, minimum games filter, `pn-row-me` (L1).
2. Top performer on the match page plus a records page (L2).
3. Form guide and head-to-head on team and match pages (T1, T2).
4. `PlayerProfile.show_on_leaderboards` opt-out on the edit profile page.
5. A "Leaderboards" entry under Standings in the navbar, not a new top-level item (DESIGN.md navbar rule).
Definition of done: demo league data shows leaders in basketball, futsal and volleyball on the testing site.

**Sprint B: "Badges and MVP" (Gamification v2)**
1. `Award` + `PlayerAward` models, admin, seeding of the award catalog (section 3.1 table).
2. `grant_awards` management command (idempotent, `--dry-run`, `--today`), cron next to `advance_season_states`.
3. Awards section on the profile and an "Achievement chip" component in DESIGN.md.
4. A notification for each new award (not for seed or demo rows, as with `seed_demo_league`).
5. Stretch: `MVPVote` with the opponents-vote rule and the top-performer fallback.

**Sprint C: "Playoffs and tournaments"**
1. `Stage` model plus `Match.stage`, `round`, `bracket_slot`, `winner`, `decided_by`.
2. A "Start playoffs" admin flow: pick the top N, preview the seeded bracket (same layout as the round-robin preview), create round 1.
3. Score form: requires a winner when scores are equal in a knockout match.
4. Auto-create the next-round match when both feeder matches have a winner (facility and time picked by the admin).
5. Bracket page (one column per round, no JS), Champion award hook into Sprint B.
Follow-up sprint: "Esports and one-day events" (Online facility, best-of-3 games through periods, self-reported results with captain confirmation, check-in).

## 6. Text mockups (in the style of the existing pages)

### 6.1 Leaderboard page (players)

Recipe: page header with a season `form-select` on the right (and division if any) → stat cards → one card with tabs per stat (DESIGN.md Tabs) → leaderboard table.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ FALL 2026 · BASKETBALL                              [Season: Fall 2026   ▾]  │
│ Leaderboards                                        [Division: All       ▾]  │
│ Player stats from matches with a final score                                 │
├──────────────────────────────────────────────────────────────────────────────┤
│ ┌ TOP SCORER ────────┐ ┌ MOST ASSISTS ──────┐ ┌ PLAYER OF THE WEEK ┐ ┌ RECORD GAME ──────┐ │
│ │ (AL) Alex Lee      │ │ (JP) Jordan Park   │ │ (SK) Sam Kim       │ │ 34 pts            │ │
│ │ 142                │ │ 41                 │ │ 28 pts · 11 reb    │ │ Riya Shah         │ │
│ │ 20.3 per game      │ │ 5.9 per game       │ │ Nov 9 – Nov 15     │ │ vs Bobcats, Oct 3 │ │
│ └────────────────────┘ └────────────────────┘ └────────────────────┘ └───────────────────┘ │
│                                                                              │
│ ┌ Player leaders ─────────────────────────────── [This season | All-time] ┐ │
│ │ [★ Points]  [Assists]  [Rebounds]  [Per game]                            │ │
│ ├────┬──────────────────────────────┬─────┬───────┬──────────┬────────────┤ │
│ │ #  │ Player                       │  GP │  Pts  │  Per game│  Best game │ │
│ ├────┼──────────────────────────────┼─────┼───────┼──────────┼────────────┤ │
│ │ 1  │ (AL) Alex Lee   [Lv 4]       │   7 │ **142**│    20.3 │         31 │ │
│ │    │ [□] Violets · Division A     │     │       │          │            │ │
│ │ 2  │ (RS) Riya Shah               │   6 │ **120**│    20.0 │         34 │ │
│ │    │ [□] Torches · Division B     │     │       │          │            │ │
│ │ 3  │ (SK) Sam Kim  ← you (violet tint, pn-row-me)                      │ │
│ │    │ [□] Bobcats · Division A     │   7 │ **118**│    16.9 │         28 │ │
│ │ …                                                                        │ │
│ ├──────────────────────────────────────────────────────────────────────────┤ │
│ │ Per game needs 3 games played. Hidden players chose not to be listed.   │ │
│ │ Page 1 of 3                                       ‹ Previous   Next ›   │ │
│ └──────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
```

Rules: no `btn-primary` on this page; the sorted column is bold; numbers are `pn-num text-end`; avatar `sm` beside each name; team logo `xs` on the meta line; placeholder players show as plain text with no link; empty state "No stats yet · Stats appear after a scorekeeper records a match."

### 6.2 Badges / awards section on the profile

Recipe: the Profile page keeps its layout. Add an "Awards" card at the top of `col-lg-4` (or under the teams card in `col-lg-8`).

```
┌ Header ──────────────────────────────────────────────────────────────────────┐
│ (AL xl)  Alex Lee                                              [Edit profile]│
│          3 teams · Basketball, Futsal · 🏆 1 championship                   │
└──────────────────────────────────────────────────────────────────────────────┘
col-lg-8                                         │ col-lg-4
┌ Teams ────────────────────────────────┐        │ ┌ Awards ─────────────── 7 of 18 ┐
│ [□] Violets  2nd of 6 · 5–1–1         │        │ │ ┌────┐ ┌────┐ ┌────┐ ┌────┐   │
│ [□] Arches   4–3–0                    │        │ │ │ 🏆 │ │ ⚽3│ │ 🛡 │ │ ⏱ │   │
└───────────────────────────────────────┘        │ │ └────┘ └────┘ └────┘ └────┘   │
┌ Season stats ─────────────────────────┐        │ │ Champion Hat   Brick Over-    │
│ Violets · Fall 2026 · GP 7            │        │ │ Fall 26  trick wall  time hero│
│ Pts 142 · Ast 21 · Reb 30             │        │ │                               │
└───────────────────────────────────────┘        │ │ ┌────┐ ┌────┐ ┌────┐          │
┌ Recent matches ───────────────────────┐        │ │ │ 🔁 │ │ 🎯 │ │ 👟 │          │
│ Violets 3–2 Bobcats · 2 Goals · ★ MVP │        │ │ └────┘ └────┘ └────┘          │
│ Violets 1–1 Torches · 1 Assist        │        │ │ Iron   First  Ever-           │
└───────────────────────────────────────┘        │ │ player of many present        │
                                                 │ ├───────────────────────────────┤
                                                 │ │ Next up (owner only)          │
                                                 │ │ Double-double  ▓▓▓▓▓░░  Pts 10 / Reb 7 best │
                                                 │ │ Veteran        ▓▓▓▓░░░  2 of 3 seasons │
                                                 │ │                               │
                                                 │ │ All awards →                  │
                                                 │ └───────────────────────────────┘
                                                 │ ┌ Kudos ───────────────── 12 ┐
                                                 │ │ Hustle 6 · Defence 4 · Leader 2 │
                                                 │ └─────────────────────────────┘
                                                 │ ┌ Details (owner only) ───────┐
                                                 │ │ N number · NetID            │
                                                 │ └─────────────────────────────┘
```

Rules: each award tile is a Tabler Icon in a rounded tile (not emoji in the real page; for example `ti-trophy`, `ti-ball-football`, `ti-shield`, `ti-clock-bolt`, `ti-repeat`, `ti-target`, `ti-shoe`), with the name under it and the date and match in a `title` and in visually-hidden text. Locked awards are not shown to other viewers. "Next up" progress shows to the owner only. Hover lift only if the tile links to the match that earned it.

## 7. Data-model notes for the top 3

### 7.1 Player leaderboards (L1): no new tables

- Query: `PlayerStat.objects.filter(match__in=counted_matches(), event_type=et, match__season=season).values("player").annotate(total=Sum("value"))`. Games played: `MatchAppearance` count over the same matches. Per game = total / GP, with GP ≥ 3.
- Group by **player**, not player + team: a player can play for two teams in different seasons. Show the team from the season in view (the stored `PlayerStat.team`).
- All-time: the same query across seasons of one sport (`match__home_team__sport=sport`).
- Add to `PlayerProfile`: `show_on_leaderboards = BooleanField(default=True)`.
- Indexes (Postgres): `PlayerStat(event_type, player)` and `MatchAppearance(player, match)`. The existing unique constraints cover `match` first, so add these two.
- Exclude players with a `PendingAccount` from ranks or show them as plain names (DESIGN.md roster rule).
- Put the logic in `matches/leaderboards.py`, beside `standings.py`.

### 7.2 Badges / awards (L3)

```python
# new app: awards
class Award(models.Model):
    """One achievement in the catalog."""
    class Scope(models.TextChoices):
        MATCH = "match", "Match"        # earned in one match (Hat trick)
        SEASON = "season", "Season"     # earned when a season closes (Iron player)
        CAREER = "career", "Career"     # across seasons (Veteran)
    code = models.SlugField(unique=True)          # "hat-trick"; the rule key in code
    name = models.CharField(max_length=50)        # "Hat trick"
    description = models.CharField(max_length=200)  # "Score 3 goals in one match."
    icon = models.CharField(max_length=40)        # "ti-ball-football"
    sport = models.ForeignKey("teams.Sport", null=True, blank=True, on_delete=models.CASCADE)
    scope = models.CharField(max_length=10, choices=Scope.choices)
    is_repeatable = models.BooleanField(default=False)  # Hat trick: yes; Veteran: no
    is_active = models.BooleanField(default=True)

class PlayerAward(models.Model):
    """One award earned by one player."""
    award = models.ForeignKey(Award, on_delete=models.CASCADE, related_name="earned")
    player = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="awards")
    match = models.ForeignKey("matches.Match", null=True, blank=True, on_delete=models.CASCADE)
    season = models.ForeignKey("teams.Season", null=True, blank=True, on_delete=models.CASCADE)
    team = models.ForeignKey("teams.Team", null=True, blank=True, on_delete=models.SET_NULL)
    earned_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [
            # one row per award per match (repeatable) or per season/career
            models.UniqueConstraint(fields=["award", "player", "match"],
                                    condition=Q(match__isnull=False), name="unique_award_per_match"),
            models.UniqueConstraint(fields=["award", "player", "season"],
                                    condition=Q(match__isnull=True, season__isnull=False), name="unique_award_per_season"),
            models.UniqueConstraint(fields=["award", "player"],
                                    condition=Q(match__isnull=True, season__isnull=True), name="unique_career_award"),
        ]
```

- Rules live in code (`awards/rules.py`, one function per `code`), not in the database. The catalog row holds the display text.
- `grant_awards` command: recompute everything, add missing rows, delete rows whose rule no longer holds (score corrections). Idempotent like the seed commands. `--dry-run`, `--today`.
- Notifications only for new rows, and none for demo data.
- Optional `Match.scored_at = DateTimeField(null=True)` (set by the score form) for scorekeeper awards and "Player of the week" windows.

### 7.3 Playoffs (F1), the base for every tournament format

```python
# teams or matches app
class Stage(models.Model):
    """One phase of a season: the league table, then a knockout."""
    class Kind(models.TextChoices):
        LEAGUE = "league", "League"            # today's round robin
        SINGLE_ELIM = "single_elim", "Single elimination"
        # later: DOUBLE_ELIM, SWISS, POOLS
    season = models.ForeignKey("teams.Season", on_delete=models.CASCADE, related_name="stages")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    name = models.CharField(max_length=50)       # "Playoffs"
    order = models.PositiveSmallIntegerField()   # 1 = league, 2 = playoffs
    team_count = models.PositiveSmallIntegerField(null=True)  # 4 or 8
    best_of = models.PositiveSmallIntegerField(default=1)     # esports later
    class Meta:
        constraints = [models.UniqueConstraint(fields=["season", "order"], name="unique_stage_order")]

class StageEntry(models.Model):
    """A team's seed in a stage, frozen from the standings at the start."""
    stage = models.ForeignKey(Stage, on_delete=models.CASCADE, related_name="entries")
    team = models.ForeignKey("teams.Team", on_delete=models.CASCADE)
    seed = models.PositiveSmallIntegerField()

# new fields on Match
stage = models.ForeignKey(Stage, null=True, blank=True, on_delete=models.CASCADE, related_name="matches")
round = models.PositiveSmallIntegerField(null=True, blank=True)        # 1 = quarter-final
bracket_slot = models.PositiveSmallIntegerField(null=True, blank=True)  # position in the round
winner = models.ForeignKey("teams.Team", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
decided_by = models.CharField(max_length=12, blank=True)  # regulation / overtime / penalties / forfeit
```

- Matches with `stage = null` are league matches. A data migration is not needed if null means "league", so existing rows stay as they are.
- `counted_matches()` for standings must exclude knockout stages (`stage__isnull=True` or `stage__kind="league"`), or playoff games change the regular-season table.
- `Match.clean()`: in a knockout stage, equal scores need a `winner`; `winner` must be home or away.
- The next round is made when both feeder slots (`bracket_slot` 2k−1 and 2k) have a winner. The team placeholder "Winner of QF1" needs either a nullable team (the `home_team` FK is PROTECT and required now) or creating the match only when both teams are known. **Create it only when both are known**: there is less schema change.
- Seeding: from `compute_standings()`, tiebreak points → wins → head-to-head → name (say this on the page).
- Champion award (7.2) reads the final's `winner`.

## 8. Ideas to avoid, and why

| Idea | Why to avoid it |
|---|---|
| Per-player Elo in team sports | One player's effect can't be separated from the team result. It ranks people unfairly. Use team Elo, and player Elo only for solo ladders. |
| XP or awards for chat messages, forum posts or logins | Rewards spam and adds moderation load. Count only scorekeeper-confirmed play. |
| Leaderboards or awards for fouls or yellow cards ("Most carded") | Rewards bad conduct; a fair-play award that counts zero cards is the safer version. |
| Pick'em, predictions or fantasy with prizes, points shops or money | Gambling laws and NYU policy. It also gives a motive to throw a match. Keep pick'em prize-free and off your own matches, or skip it. |
| Public no-show lists or "reliability scores" for people | Shames students and invites disputes. Show RSVP to teammates only; handle forfeits at team level. |
| Photo uploads before S3 and a report flow | Consent, NSFW content and storage cost. DESIGN.md already defers uploads. |
| GPS tracks or live location (Strava-style) for run clubs | Shows where students live and walk. Log distance only. |
| Follows of individual people with open DMs | Stalking and harassment risk on a campus app. Team follows only; DMs keep the `Block` rules. |
| Anonymous ratings of individual players | Bullying with no accountability. Sportsmanship ratings rate teams, by the scorekeeper, with admin review. |
| Realtime features (live scores, typing indicators) through websockets | Needs Channels, Redis and a different EB setup. Page refresh and a "Refresh" link (the chat pattern) are enough. |
| Building every tournament format at once (double elimination, Swiss, pools) | Each format has edge cases. Build single elimination, then pools to playoffs, then the rest only if someone runs them. |
| Game API integrations (Riot, Steam, chess.com) for esports | API keys, terms, rate limits and upkeep. Use self-reported results confirmed by the other captain and links to match pages. |
| A separate "events" product that copies NYU's own class booking | Duplicates the system of record and goes stale. Link out for classes; only build RSVP for events PlayNYU runs. |
| Polls and recurring availability grids in the first waves | Low use next to per-match RSVP; they add UI without solving a top problem. |
