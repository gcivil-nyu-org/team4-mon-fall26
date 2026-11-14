# Add players by email before they sign up, and a class league seed

## Intent

Captains add a player by NYU email even when that player has no account yet. The site tracks that player's matches and records right away. The player claims the spot when they sign up with that email. A seed command uses the same mechanism to fill a demo league from a roster file kept out of git.

## Goals

- A captain adds any `@nyu.edu` email. With no account, the site creates a placeholder account and puts it on the roster.
- A placeholder is an inactive user with an unusable password and a `PendingAccount` row.
- Sign-up with a placeholder email claims the placeholder: same user, same teams and history.
- The claim completes only when the email link is opened. The `PendingAccount` row is then deleted.
- The site emails a new placeholder once: "you were added to <team>, sign up to join".
- Rosters show players who have not signed up with a "Not signed up yet" badge and no profile link.
- A new sport added by a League Admin gets its current and next semester default seasons at once.
- `seed_class_league --roster <file>` creates teams, placeholder players and a half-played schedule in the current semester's default seasons. The `leader` team wins its played matches.

## Non-goals

- No accept/decline step for invites.
- No roster data in the repo. The roster file stays outside git (the repo is public).

## Anti-goals

- Typing someone's email must never let a person take over that account.
- The add-player form must not reveal whether an email has an account.

## Approaches

- **Placeholder user accounts (picked).** Every existing query (rosters, standings, chat, notifications) keeps working on a real `User` row.
- An `Invite` table with roster rows pointing at either a user or an invite. Every roster query would need two cases.
- Invites that create the roster row only on sign-up. Matches played before sign-up would not count for the player.

## Decisions

- Captains add players. League Admins use the same page through the existing rules.
- `accounts/placeholders.py` holds `placeholder_for(email, first_name="", last_name="", invited_by=None)` → `(user, created)`.
- Verification refuses a user without a usable password, so a resent link can't activate an unclaimed placeholder.
- The class league roster file format is in the seed command's docstring.

## Left to the builder

- Wording of messages, the invite email and help text.
- Test layout, following existing `*/test_*.py` style.
