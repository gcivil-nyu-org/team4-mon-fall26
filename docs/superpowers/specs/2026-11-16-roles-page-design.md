# Roles page: League Admins grant and remove roles

Status: draft 2026-11-16, for issue #261 (parent epic #31). Read from `origin/testing` at `b46da2d`.

## Intent

Today only a superuser can grant Scorekeeper or League Admin, in `/admin/`. A League Admin who schedules a match and finds no scorekeeper in the list can do nothing about it.

This page lets League Admins give and take away the two staff roles, with rules that keep the league from locking itself out, and a record of every change.

## Goals

- A League Admin page lists active, signed-up users with their roles. It has a name search, a role filter and paging (20 rows).
- Each row has one POST button per role: add or remove Scorekeeper, add or remove League Admin.
- The last League Admin can't be removed. Nobody can remove their own League Admin role.
- Two admins who act at the same time can't leave the league with no League Admin.
- Each change writes one audit row and sends the user one notification.
- Non-admins get 403. Placeholders and inactive users are not listed and can't be changed (404).
- League setup and the Overview quick links open the page. The match form's scorekeeper field links to it.

## Non-goals

- No Casual Player management. Every verified user gets it (`accounts/views.py:_activate`), and no view checks it. The page does not show it.
- No superuser management. The page never sets `is_superuser` or `is_staff`.
- No new top-level nav item. `docs/DESIGN.md` "Navbar": "Do not add a top-level item for one admin page."
- No change to how matches keep a scorekeeper who loses the role (see Rules, R7).
- No audit of role changes made in `/admin/` or by seed commands. Only this page logs.
- No bulk actions and no JavaScript.
- No confirm step. Every change is reversible from the same row, and the audit log records it.

## Approaches

1. **A custom page in `accounts`, one POST per role change (recommended).** One list view and one POST view. The safety rules, the lock, the audit row and the notification live in one service function. It fits the existing League Admin pages (event types, moderation queue) and DESIGN.md.
2. **Open `/admin/` to League Admins** (`is_staff` plus `change_user` permission). No new UI, but the admin can't enforce the last-admin or self rules, lists placeholders and inactive users, shows every group, and lets a League Admin edit passwords, emails and superuser flags. Rejected: unsafe and off-design.
3. **A per-user edit page with two checkboxes.** One form sets both roles. It needs a second page and two clicks per change. One POST can then change two roles, so the audit, notification and refusal rules each need a "both" case. Rejected: more code, no gain.

## Rules

**R1. Who sees the page.** `request.user.is_superuser or has_role(request.user, LEAGUE_ADMIN_ROLE)`. This is the same gate as `_require_league_admin` in `teams/views.py`. Anonymous users go to login (302). Everyone else gets 403.

**R2. Who is listed.** `is_active=True` and no `PendingAccount` row (`pending_account__isnull=True`). Placeholders are inactive anyway (`accounts/placeholders.py`). The second filter keeps a broken row out too. Unverified sign-ups are inactive, so they drop out. Superusers are listed like anyone else.

**R3. Search, filter, paging.**
- `q`: each word must match `first_name`, `last_name` or `email` (`icontains`). "alex lee" finds Alex Lee. Up to 100 characters.
- `role`: `""` (All people), `scorekeeper`, `league_admin`. Any other value is ignored, not a 400.
- Order: `first_name`, `last_name`, `email`, `pk`.
- `Paginator(qs, 20).get_page(page)`. The pager keeps `q` and `role` (`components/pager.html`).

**R4. Actions.** `POST /accounts/roles/<user_pk>/` with `role` (`scorekeeper` or `league_admin`) and `action` (`add` or `remove`), plus CSRF. GET gives 405. A bad `role` or `action` gives 400. A target outside R2 gives 404. After the change, redirect to the list with the same `q`, `role` and `page`.

**R5. Idempotent.** Adding a role the user has, or removing one they don't have, changes nothing. It writes no audit row and sends no notification. The message says "Alex Lee is already a Scorekeeper."

**R6. Safety rules for League Admin removal.**
- A user can't remove their own League Admin role. This applies to superusers too, for one simple rule. Message: "You can't remove your own League Admin role. Ask another League Admin."
- The last League Admin can't be removed. Message: "Alex Lee is the last League Admin. Make someone else a League Admin first."
- **How superusers count:** the count is the users who hold the League Admin group and pass R2. `is_superuser` neither adds nor subtracts. Why: a superuser is a developer or ops account, made with `createsuperuser`. It may not exist on every site. It may be shared. It acts through `/admin/`, not as a league role. If superusers counted, the league could end with no person in the League Admin role and no one would notice. A superuser who also holds the group counts, because they hold the role.
- A superuser row shows a `Site admin` badge. Its hint says that this user has League Admin access whether or not they hold the role.
- The actor is checked again inside the lock. An admin whose own role was removed a moment ago gets 403, even if the gate passed before.

**R7. A scorekeeper who loses the role.** Keep the assignment. This is what the code already does:
- `Match.scorekeeper` comment (`matches/models.py`): "Losing the role keeps the link so past matches stay accurate, so anything that acts for a scorekeeper must check the role too."
- `submit_score` and `my_matches` check `has_role(SCOREKEEPER_ROLE)`. `_score_url` checks it too. A removed scorekeeper can't score.
- `MatchForm` keeps the current scorekeeper selectable, and `Match.clean` rejects only a new assignment of a non-Scorekeeper.
- `manage_matches.html` shows a `Needs reassigning` badge on live matches whose scorekeeper lost the role.

Unassigning would erase "Kept score by" history on ended, unscored matches, and lose the assignments when an admin removes the role by mistake and adds it back. So the page warns instead:
- Each row shows "Assigned to N unscored matches" when N > 0. "Unscored" means scheduled, no result, in a season that allows scheduling (the same live states as `MatchQuerySet.needing_score`), at any time.
- When the user has no Scorekeeper role and N > 0, the row also shows `badge bg-yellow-lt` "Needs reassigning", the same badge as Manage matches.
- After a removal with N > 0, a warning message: "Alex Lee still has 3 unscored matches and can't score them now. Choose another scorekeeper on Manage matches."

**R8. Concurrency.** Admins A and B remove each other at the same time. Each sees 2 League Admins, each removal passes, and the league has none.

Fix: every role change runs in `transaction.atomic()` and first locks the role's `Group` row: `Group.objects.select_for_update().get(name=role_name)`. All changes to one role queue on that one row. After the lock, the service reads the actor's access, the target's current membership and the League Admin count again. Under Postgres READ COMMITTED each new statement sees the rows that the earlier transaction committed. So B, after waiting, counts 1 and is refused (or fails the actor check).

Why not lock the user rows: the holder query joins `auth_user_groups`. When a blocked `SELECT ... FOR UPDATE` wakes up, Postgres re-checks only the locked rows. It does not re-read the joined membership rows, so B could still count A's removed row. It would also need `of=("self",)` for the outer join on `pending_account` (`docs/DATABASE.md`).

SQLite ignores `select_for_update` (`docs/DATABASE.md`). The local and CI SQLite settings use `transaction_mode: IMMEDIATE` (`playnyu/database.py`), so each `atomic()` block takes the write lock at `BEGIN` and the blocks run one after another. The rule holds on both databases. The lock is tested on Postgres only (`skipUnlessDBFeature("has_select_for_update")`).

**R9. Emails (recommended: show them, labelled).** Two people can share a name, and a nameless user shows as "PlayNYU player". Granting League Admin to the wrong one gives away the whole league. The email is the only field that tells accounts apart for sure, so on this page the email is "the point of the field" (DESIGN.md "Person names").
- Each row shows `<span class="visually-hidden">Email: </span>alex@nyu.edu` in the secondary line. Only this page shows it, and only League Admins and superusers can open it.
- Search matches the email too.
- Messages, audit rows and notifications use `display_name` only, never the email.
- DESIGN.md "Person names" names the roles page as an allowed place for the email.

Options not picked: no email at all (nameless users can't be told apart); NetID (it is an owner-only profile field, and it can be blank); team names (many users have no team).

**R10. Casual Player.** Not shown and not accepted by the POST (400).

## URLs/views

| URL | Name | View | Method |
|---|---|---|---|
| `/accounts/roles/` | `accounts:roles` | `accounts.role_views.role_list` | GET |
| `/accounts/roles/<int:user_pk>/` | `accounts:change_role` | `accounts.role_views.change_role` | POST (`require_POST`) |

New module `accounts/role_admin.py` (the service; `accounts/roles.py` stays small because `matches/models.py` imports it):

- `MANAGED_ROLES = {"scorekeeper": SCOREKEEPER_ROLE, "league_admin": LEAGUE_ADMIN_ROLE}`
- `can_manage_roles(user) -> bool`
- `listable_users() -> QuerySet` (R2)
- `league_admin_count() -> int` (R6)
- `unscored_match_count(user) -> int` (R7)
- `role_rows() -> QuerySet`: `listable_users()` with `is_scorekeeper`, `is_league_admin` (`Exists`) and `unscored_matches` (a `Subquery` count) annotations, in R3 order.
- `change_role(actor, target, role_name, grant) -> bool`: R5, R6, R8. Returns True when it changed something. Raises `RoleChangeRefused(message)` or `PermissionDenied`. Writes the audit row and sends `role_changed` inside the transaction.
- `role_changed = Signal()`, sent with `user`, `role`, `granted`, `actor`.

`MatchQuerySet.unscored()` in `matches/models.py`: scheduled, no result, live season. `needing_score` stays as it is.

`RoleFilterForm` in `accounts/forms.py`: `q` (`CharField`, optional, `max_length=100`, strip) and `role` (`ChoiceField`, optional). `auto_id="roles_%s"`.

The list view sets `nav_section = "league_setup"`. Its query count is fixed for any page size.

## Templates (sketches)

`accounts/templates/accounts/roles.html`, layout like Event types: page header, then `col-lg-8` list and `col-lg-4` help card. No `btn-primary`: every action is a row action.

Desktop (≥ 992px):

```
League Admin
Roles                                                            [League setup]
Who keeps score and who runs the league.

┌─────────────────────────────────────────────────────┐ ┌──────────────────────────┐
│ Search [Name or email         ] Role [All people ▾] │ │ About roles              │
│ [Filter]                                            │ │ Scorekeeper              │
├─────────────────────────────────────────────────────┤ │  Records scores for the  │
│ People                                   42 people  │ │  matches assigned to them│
├─────────────────────────────────────────────────────┤ │ League Admin             │
│ (AL) Alex Lee  [League Admin] [Scorekeeper]         │ │  Runs every League Admin │
│      alex@nyu.edu · Assigned to 3 unscored matches  │ │  page, this one included │
│                 [Remove Scorekeeper] [Remove League │ │ Rules                    │
│                  Admin]                             │ │  · The league keeps at   │
│ (PP) PlayNYU player                                 │ │    least one League Admin│
│      noname@nyu.edu                                 │ │  · You can't remove your │
│                 [Add Scorekeeper] [Add League Admin]│ │    own League Admin role │
│ (LA) Lee Admin  [League Admin] [Site admin]  (you)  │ │  · Site admins have      │
│      boss@nyu.edu                                   │ │    League Admin access   │
│                 [Add Scorekeeper] [Remove League    │ │    without the role      │
│                  Admin] (disabled: your own role)   │ │                          │
│ (SK) Sam Kim  [Needs reassigning]                   │ │                          │
│      sam@nyu.edu · Assigned to 2 unscored matches   │ │                          │
│                 [Add Scorekeeper] [Add League Admin]│ │                          │
├─────────────────────────────────────────────────────┤ └──────────────────────────┘
│ Page 1 of 3                    < Previous   Next >  │
└─────────────────────────────────────────────────────┘
```

Phone (375px): the columns stack, the help card goes under the list, and each row's buttons wrap under the name.

```
League Admin
Roles
Who keeps score and who runs the league.
[League setup]

┌───────────────────────────────┐
│ Search                        │
│ [Name or email              ] │
│ Role                          │
│ [All people               ▾ ] │
│ [Filter]                      │
├───────────────────────────────┤
│ People              42 people │
├───────────────────────────────┤
│ (AL) Alex Lee                 │
│      [League Admin]           │
│      [Scorekeeper]            │
│      alex@nyu.edu             │
│      Assigned to 3 unscored   │
│      matches                  │
│ [Remove Scorekeeper]          │
│ [Remove League Admin]         │
├───────────────────────────────┤
│ Page 1 of 3   < Prev  Next >  │
└───────────────────────────────┘
┌───────────────────────────────┐
│ About roles  ...              │
└───────────────────────────────┘
```

Markup rules:
- The filter is a GET form in the People card's `card-body`, the same as Teams directory: `row g-2 align-items-end`, `col-sm-6` for each field, Filter as `btn btn-outline-secondary`.
- Each row: `list-group-item d-flex flex-wrap align-items-center gap-3`. Avatar `sm`. Name `fw-medium` with `display_name`. Role badges `badge bg-primary-lt` "League Admin" and "Scorekeeper". `badge bg-secondary-lt` "Site admin" with a `title`. The viewer's own row gets `pn-row-me` and a visually-hidden " (you)".
- The secondary line is `small text-secondary text-break`: the email, then "· Assigned to N unscored match(es)" with `pn-num`.
- Buttons: one `<form method="post">` for each button, with `{% csrf_token %}`, hidden `role`, `action`, `q`, `role_filter` and `page`. Add is `btn btn-sm btn-outline-secondary` with `ti-user-plus`. Remove is `btn btn-sm btn-ghost-danger` with `ti-user-minus`. The label is the visible verb and role ("Remove Scorekeeper"), plus `<span class="visually-hidden"> for Alex Lee</span>`.
- A refused remove renders `disabled`, with the reason in `title` and in a `visually-hidden` span: "You can't remove your own League Admin role" or "The league needs at least one League Admin". The server enforces the rule anyway.
- Empty state: "No one matches these filters." with a "Clear filters" link when `q` or `role` is set, else "No signed-up users yet."
- Buttons are at least 40px tall below 768px (DESIGN.md §8). `btn-sm` in a list row already meets this through the `.list-group-item .btn-sm` rule if one exists. If not, add a rule under a `/* Roles page */` comment in `playnyu.css`.

Entry points:
- League setup: a "Roles" card (`ti-shield-check`) with "N League Admin(s) · M Scorekeeper(s)". Add "roles" to the page-meta list.
- Overview quick links: "Roles" (`ti-shield-check`), after "Moderation queue".
- Match form: the scorekeeper field's help text. With no Scorekeepers: "No one has the Scorekeeper role yet. <a>Grant the role</a>". Otherwise: "Only Scorekeepers are listed. <a>Manage roles</a>". `form_fields.html` renders help text with `|safe`, so build it with `format_html`.

DESIGN.md: add a "Roles (League Admin)" page recipe, and name the roles page in "Person names" as a place that shows the email.

## Audit and notifications

**Audit.** Add two `AuditLog.Action` choices: `GRANTED = "granted", "Granted"` and `REMOVED = "removed", "Removed"`. This adds a choices-only migration, `audit/0002_alter_auditlog_action`. Each change writes one row:

| Field | Value |
|---|---|
| `actor` | the admin |
| `action` | `granted` or `removed` |
| `object_type` | `"Role"` |
| `object_id` | `str(target.pk)` |
| `object_repr` | `"Scorekeeper to Alex Lee"` or `"Scorekeeper from Alex Lee"` (`display_name`, max 200 characters) |

The overview's Recent changes then reads "Granted role Scorekeeper to Alex Lee". `Updated user ...` would read worse, and filtering role changes later would need a parse of `object_repr`. The Recent changes empty state adds "roles" to its list. The row is written in the service and not by a signal, because `user.groups` changes come from many places (sign-up adds Casual Player).

**Notifications.** `notifications/signals.py` connects to `accounts.role_admin.role_changed`. It uses `_notify_ids`, so `muted()` still works. It sends to the target only:

| Change | Verb | Link |
|---|---|---|
| Scorekeeper added | "Lee Admin made you a Scorekeeper. Your matches are on My matches." | `matches:mine` |
| League Admin added | "Lee Admin made you a League Admin." | `core:overview` |
| Scorekeeper removed | "Lee Admin removed your Scorekeeper role." | none |
| League Admin removed | "Lee Admin removed your League Admin role." | none |

The actor name is `display_name(actor)`. A change by the user on their own row (for example, a League Admin who adds Scorekeeper to themselves) still notifies them. It is harmless, and the rule stays simple.

## Tests

Service (`accounts/test_role_admin.py`):
- Add Scorekeeper adds the group, writes one `granted` audit row with the exact `object_repr`, and sends one notification with the verb and link above.
- Each of the four changes: verb, link, audit action.
- Adding twice: the second call returns False, with no second audit row or notification. The same for removing a role the user doesn't have.
- Self-removal of League Admin is refused, also for a superuser.
- The last League Admin can't be removed by a superuser who doesn't hold the role.
- An inactive holder and a placeholder holder don't count: with one active holder and one inactive holder, removing the active one is refused.
- A superuser who holds the group counts: a League Admin can remove the other holder.
- An actor who no longer has access gets `PermissionDenied`.
- `Casual Player` is not accepted (`ValueError`).
- Removing Scorekeeper keeps `match.scorekeeper` and `unscored_match_count` stays the same.
- `unscored_match_count` counts scheduled, unscored, live-season matches only (cancelled, scored, draft and closed are left out).
- Postgres only: `change_role` sends `SELECT ... FOR UPDATE` on `auth_group` (`CaptureQueriesContext`).
- Postgres only (`TransactionTestCase`): two threads, A removing B and B removing A, start together behind a `threading.Barrier`. Exactly one succeeds, and one League Admin is left.

List view (`accounts/test_role_views.py`):
- Anonymous 302 to login. Casual Player 403. Scorekeeper 403. League Admin 200. Superuser 200.
- Placeholder and inactive users are not listed.
- Search by first name, last name, "first last" and email. The role filter shows only holders. `?role=bogus` shows everyone with 200.
- 21 users give 2 pages. The page-2 link keeps `q` and `role`.
- The email shows with the "Email:" label. A nameless user shows "PlayNYU player".
- The viewer's own League Admin remove button is disabled. With one League Admin, that row's button is disabled.
- Superuser rows show `Site admin`. A user with unscored matches shows the count. A non-Scorekeeper with unscored matches shows `Needs reassigning`.
- Query count: the same for 2 listed users and for 20 (`CaptureQueriesContext`, compare lengths).
- `nav_section` highlights League setup.

POST view:
- GET gives 405. A Casual Player gets 403 and nothing changes.
- With `Client(enforce_csrf_checks=True)` and no token, the POST gives 403.
- A placeholder or inactive target gives 404. A bad `role` or `action` gives 400.
- Redirect keeps `q`, `role` and `page`. Success, info, error and warning messages carry the exact copy above.

Entry points and others:
- League setup links `accounts:roles` and shows the counts. The Overview quick links link it.
- The match form help text links `accounts:roles` in both variants.
- The Overview Recent changes shows "Granted role Scorekeeper to Alex Lee".
- `core/test_no_email_names.py`: the roles page shows "PlayNYU player", and the email appears only in the labelled field.
- `makemigrations --check` passes with the audit migration in place.

## Decisions

The user approved each recommendation on 2026-11-16.

1. **Emails show on the roles page.** League Admins see the email in each row, after a visually hidden "Email:" label. Search matches the email. DESIGN.md "Person names" lists the roles page as an allowed place (R9).
2. **Superusers do not count toward the last League Admin** unless they hold the group. A superuser row shows a "Site admin" badge (R6).
3. **A scorekeeper who loses the role keeps their matches.** The row shows the unscored count and the badge, and the removal shows a warning (R7).
4. **New audit actions `granted` and `removed`**, with a choices-only migration, `audit/0002_alter_auditlog_action`.
5. **Do not notify the other League Admins.** The target's notification and the overview's Recent changes are enough.
