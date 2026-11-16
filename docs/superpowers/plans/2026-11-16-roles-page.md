# Roles page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** League Admins and superusers grant and remove the Scorekeeper and League Admin roles on `/accounts/roles/`, with safety rules, an audit row and a notification for each change (#261).

**Architecture:** One service module, `accounts/role_admin.py`, holds the rules. It locks the role's `Group` row, checks the rules again, changes the membership, writes the `AuditLog` row and sends a `role_changed` signal. `notifications/signals.py` turns the signal into a notification. Two thin views in `accounts/role_views.py` list users and accept one POST per change. League setup, the Overview and the match form link the page.

**Tech Stack:** Django 5 templates, Tabler (Bootstrap 5), Django `TestCase` / `TransactionTestCase`, `coverage`, SQLite (CI with coverage) and Postgres (CI second run).

**Spec:** `docs/superpowers/specs/2026-11-16-roles-page-design.md`

## Global Constraints

- Branch: `nihal/roles-and-sport-periods`, from `origin/testing`. The branch also carries #262 (sport periods). Do not touch `teams/models.py`, `teams/migrations/`, `teams/management/commands/seed_league_data.py` or sport period code.
- Every commit message starts with `#261:`. No `Co-Authored-By` line and no footer that names Claude.
- Never commit to `main` or `testing`.
- Names come from `core.names.display_name` (`|display_name` in templates). The email shows only in the roles page row, after `<span class="visually-hidden">Email: </span>`. Messages, audit rows and notifications never contain an email.
- Listed and changeable users: `is_active=True` and `pending_account__isnull=True`.
- Managed roles: `MANAGED_ROLES = {"scorekeeper": SCOREKEEPER_ROLE, "league_admin": LEAGUE_ADMIN_ROLE}`. Casual Player is never shown or accepted.
- Superusers do not count toward the League Admin count unless they hold the group.
- 20 rows per page.
- Follow `docs/DESIGN.md`. No `btn-primary` on the roles page. No `<style>` block, no hex colors.
- One migration only: `audit/migrations/0002_alter_auditlog_action.py`.
- CI: `black --check .`, `flake8 .`, `coverage run manage.py test`, `coverage report --fail-under=80`, `python manage.py makemigrations --check --dry-run`.

Exact copy (from the spec):

| Key | Text |
|---|---|
| granted | `{name} is now a Scorekeeper.` / `{name} is now a League Admin.` |
| removed | `{name} is no longer a Scorekeeper.` / `{name} is no longer a League Admin.` |
| already | `{name} is already a Scorekeeper.` / `{name} isn't a Scorekeeper.` (same with League Admin) |
| self | `You can't remove your own League Admin role. Ask another League Admin.` |
| last | `{name} is the last League Admin. Make someone else a League Admin first.` |
| stranded | `{name} still has {n} unscored match(es) and can't score them now. Choose another scorekeeper on Manage matches.` |
| notify SK add | `{actor} made you a Scorekeeper. Your matches are on My matches.` link `matches:mine` |
| notify LA add | `{actor} made you a League Admin.` link `core:overview` |
| notify remove | `{actor} removed your Scorekeeper role.` / `{actor} removed your League Admin role.` no link |
| audit repr | `Scorekeeper to {name}` (granted) / `Scorekeeper from {name}` (removed) |

## Review Focus

1. Two admins remove each other at the same moment on Postgres: one must be refused, and one League Admin must be left. Task 3 tests this with two threads.
2. A user with no name: the row shows "PlayNYU player" and the email in the labelled field. Messages, audit rows and notifications say "PlayNYU player" and never the email. Tasks 2 and 4 test this.
3. A stale or hand-made URL (`?role=bogus`, `?page=999`, `?q=` with 200 characters, a POST with `role=casual_player`): the list gives 200 and drops the bad value; the POST gives 400. Tasks 4 and 5 test this.
4. A double click on "Add Scorekeeper" (two POSTs): one audit row and one notification only. Task 2 tests this through the service, and Task 5 through the view.
5. A removal from page 3 with a search: the redirect comes back to page 3 with the same search and filter, not to page 1. Task 5 tests this.

---

### Task 0: Branch

- [ ] **Step 1: Get the branch**

If `nihal/roles-and-sport-periods` exists (the #262 planner may have made it), check it out and rebase it on `origin/testing`. If it does not exist, create it:

```bash
git fetch origin
git checkout nihal/roles-and-sport-periods 2>/dev/null || git checkout -b nihal/roles-and-sport-periods origin/testing
```

Expected: you are on `nihal/roles-and-sport-periods`, and `git log origin/testing..HEAD` shows only #262 commits, or none.

---

### Task 1: Audit actions for role changes

**Files:**
- Modify: `audit/models.py` (`AuditLog.Action`, class docstring)
- Create: `audit/migrations/0002_alter_auditlog_action.py` (generated)
- Test: `audit/tests.py` (add class `RoleActionTests`)

**Interfaces:**
- Produces: `AuditLog.Action.GRANTED == "granted"` (label "Granted"), `AuditLog.Action.REMOVED == "removed"` (label "Removed").

- [ ] **Step 1: Write the failing tests**

```python
class RoleActionTests(TestCase):
    def test_role_actions_exist(self):
        self.assertEqual(AuditLog.Action.GRANTED, "granted")
        self.assertEqual(AuditLog.Action.GRANTED.label, "Granted")
        self.assertEqual(AuditLog.Action.REMOVED, "removed")
        self.assertEqual(AuditLog.Action.REMOVED.label, "Removed")

    def test_role_row_saves(self):
        row = AuditLog.objects.create(
            action=AuditLog.Action.GRANTED, object_type="Role",
            object_id="7", object_repr="Scorekeeper to Alex Lee",
        )
        self.assertEqual(row.get_action_display(), "Granted")
```

- [ ] **Step 2: Run and see them fail**

Run: `python manage.py test audit.tests.RoleActionTests`
Expected: `AttributeError: GRANTED`

- [ ] **Step 3: Add the two choices**

Add `GRANTED` and `REMOVED` after `DELETED`. Change the docstring to: "One row per League Admin change to a Team, Season, Sport, Match or Facility, or to a user's role." Then run `python manage.py makemigrations audit -n alter_auditlog_action`.

- [ ] **Step 4: Run and see them pass**

Run: `python manage.py test audit && python manage.py makemigrations --check --dry-run`
Expected: `OK`, then `No changes detected`.

- [ ] **Step 5: Commit**

```bash
git add audit/models.py audit/migrations/0002_alter_auditlog_action.py audit/tests.py
git commit -m "#261: Add granted and removed audit actions for role changes"
```

---

### Task 2: The role service

**Files:**
- Create: `accounts/role_admin.py`
- Modify: `matches/models.py` (add `MatchQuerySet.unscored`)
- Test: `accounts/test_role_admin.py` (create)

**Interfaces:**
- Consumes: `AuditLog.Action.GRANTED` / `REMOVED` (Task 1).
- Produces, in `accounts/role_admin.py`:
  - `MANAGED_ROLES: dict[str, str]` (see Global Constraints).
  - `class RoleChangeRefused(Exception)`: `str(error)` is the user-facing message.
  - `role_changed = Signal()`: sent with `user`, `role` (group name), `granted` (bool), `actor`.
  - `can_manage_roles(user) -> bool`: `is_superuser` or `has_role(user, LEAGUE_ADMIN_ROLE)`.
  - `listable_users() -> QuerySet[User]`: active, no `PendingAccount`.
  - `league_admin_count() -> int`: `listable_users()` in the League Admin group, `.distinct().count()`.
  - `unscored_match_count(user) -> int`: `Match.objects.unscored().filter(scorekeeper=user).count()`.
  - `change_role(actor, target, role_name, grant) -> bool`: True when something changed. Raises `ValueError` for a role not in `MANAGED_ROLES.values()`, `PermissionDenied` when the actor can't manage roles, and `RoleChangeRefused` for the self and last rules.
- Produces, in `matches/models.py`: `MatchQuerySet.unscored()`: `self.scheduled()`, either score null, `season__state__in` the live states. Use the same live-state list as `needing_score`. Lift it into a module-level helper `_live_season_states()` that both methods call. Do not change what `needing_score` returns.

- [ ] **Step 1: Write the failing tests** in `accounts/test_role_admin.py`.

Fixtures: a local `make_user(email, first="", last="", role=None, **extra)` like `teams/test_perm_sweep_teams.py`, using `create_user(username=email, email=email, ...)`. Users: `boss` (League Admin, "Lee Admin"), `alex` ("Alex Lee"), `nameless` (no name), a placeholder via `accounts.placeholders.placeholder_for("ghost@nyu.edu")`, and `root` (`create_superuser`, no group). Match fixtures follow `make_match` in `core/test_no_email_names.py`.

```python
class ChangeRoleTests(TestCase):
    def test_grant_scorekeeper_adds_group_audit_and_notification(self):
        self.assertTrue(change_role(self.boss, self.alex, SCOREKEEPER_ROLE, True))
        self.assertTrue(has_role(self.alex, SCOREKEEPER_ROLE))
        row = AuditLog.objects.get(object_type="Role")
        self.assertEqual((row.actor, row.action, row.object_id, row.object_repr),
                         (self.boss, "granted", str(self.alex.pk), "Scorekeeper to Alex Lee"))
        note = Notification.objects.get(recipient=self.alex)
        self.assertEqual(note.verb, "Lee Admin made you a Scorekeeper. Your matches are on My matches.")
        self.assertEqual(note.link, reverse("matches:mine"))

    def test_remove_writes_removed_row(self): ...        # object_repr "Scorekeeper from Alex Lee"
    def test_second_grant_changes_nothing(self): ...     # returns False; 1 audit row, 1 notification
    def test_removing_a_missing_role_changes_nothing(self): ...
    def test_nameless_target_uses_fallback_name(self):
        change_role(self.boss, self.nameless, SCOREKEEPER_ROLE, True)
        self.assertEqual(AuditLog.objects.get().object_repr, "Scorekeeper to PlayNYU player")
    def test_casual_player_is_rejected(self):
        with self.assertRaises(ValueError):
            change_role(self.boss, self.alex, CASUAL_PLAYER_ROLE, True)
    def test_actor_without_access_is_denied(self):
        with self.assertRaises(PermissionDenied):
            change_role(self.alex, self.nameless, SCOREKEEPER_ROLE, True)

class LeagueAdminRuleTests(TestCase):
    def test_self_removal_is_refused(self):
        assign_role(self.alex, LEAGUE_ADMIN_ROLE)  # two holders, so only the self rule applies
        with self.assertRaisesMessage(RoleChangeRefused,
                "You can't remove your own League Admin role. Ask another League Admin."):
            change_role(self.boss, self.boss, LEAGUE_ADMIN_ROLE, False)
    def test_superuser_self_removal_is_refused(self): ...   # root holds the group plus boss
    def test_last_admin_is_refused_even_for_a_superuser(self):
        with self.assertRaisesMessage(RoleChangeRefused,
                "Lee Admin is the last League Admin. Make someone else a League Admin first."):
            change_role(self.root, self.boss, LEAGUE_ADMIN_ROLE, False)
    def test_inactive_and_placeholder_holders_do_not_count(self): ...  # both hold the group; still refused
    def test_superuser_holding_the_group_counts(self): ...  # root in group -> root removes boss -> True
    def test_league_admin_count(self): ...                 # 1; root without group adds 0

class ScorekeeperMatchTests(TestCase):
    def test_removal_keeps_the_assignment(self):
        match = self.make_match(scorekeeper=self.alex)  # alex has the role first
        change_role(self.boss, self.alex, SCOREKEEPER_ROLE, False)
        match.refresh_from_db()
        self.assertEqual(match.scorekeeper, self.alex)
        self.assertEqual(unscored_match_count(self.alex), 1)
    def test_unscored_counts_live_unscored_scheduled_only(self): ...
        # subTest per left-out case: cancelled, scored, draft season, closed season -> 0
        # a past ended unscored match in an active season -> counted
```

- [ ] **Step 2: Run and see them fail**

Run: `python manage.py test accounts.test_role_admin`
Expected: `ModuleNotFoundError: No module named 'accounts.role_admin'`

- [ ] **Step 3: Implement `matches/models.py` `unscored()` and `accounts/role_admin.py`**

`change_role` order. This order is the R8 fix, so keep it:

```python
if role_name not in MANAGED_ROLES.values():
    raise ValueError(role_name)
with transaction.atomic():
    group, _ = Group.objects.select_for_update().get_or_create(name=role_name)
    if not can_manage_roles(actor):          # read again under the lock
        raise PermissionDenied("League Admin access is required.")
    held = target.groups.filter(pk=group.pk).exists()
    if held == grant:
        return False
    if not grant and role_name == LEAGUE_ADMIN_ROLE:
        if target.pk == actor.pk:
            raise RoleChangeRefused(SELF_MESSAGE)
        if league_admin_count() <= 1:
            raise RoleChangeRefused(LAST_MESSAGE.format(name=display_name(target)))
    (target.groups.add if grant else target.groups.remove)(group)
    AuditLog.objects.create(...)              # see the copy table
    role_changed.send(sender=change_role, user=target, role=role_name, granted=grant, actor=actor)
return True
```

`can_manage_roles` must not use a cached group list: `has_role` runs a fresh query, which is what you need. `accounts/role_admin.py` may import `audit.models` and `matches.models`. `accounts/roles.py` must not import `role_admin`, because `matches/models.py` imports `roles`.

Leave the `Notification` assertions out of this task's tests (drop the last three lines of the first test). Task 3 adds them with the receiver.

- [ ] **Step 4: Run and see them pass**

Run: `python manage.py test accounts.test_role_admin matches`
Expected: `OK`. The `needing_score` tests in `core/test_overview.py` still pass: `python manage.py test core.test_overview`.

- [ ] **Step 5: Commit**

```bash
git add accounts/role_admin.py accounts/test_role_admin.py matches/models.py
git commit -m "#261: Add the role change service with the League Admin safety rules"
```

---

### Task 3: Notifications and the lock

**Files:**
- Modify: `notifications/signals.py` (one receiver)
- Test: `accounts/test_role_admin.py` (add `RoleNotificationTests`, `RoleLockTests`, `RoleRaceTests`)

**Interfaces:**
- Consumes: `role_changed`, `change_role` (Task 2).
- Produces: receiver `role_changed_handler(sender, user, role, granted, actor, **kwargs)` in `notifications/signals.py`. It calls `_notify_ids({user.pk}, verb, link)`.

- [ ] **Step 1: Write the failing tests**

```python
class RoleNotificationTests(TestCase):
    def test_each_change_sends_its_verb_and_link(self):
        cases = [
            (SCOREKEEPER_ROLE, True, "Lee Admin made you a Scorekeeper. Your matches are on My matches.", reverse("matches:mine")),
            (LEAGUE_ADMIN_ROLE, True, "Lee Admin made you a League Admin.", reverse("core:overview")),
            (SCOREKEEPER_ROLE, False, "Lee Admin removed your Scorekeeper role.", ""),
            (LEAGUE_ADMIN_ROLE, False, "Lee Admin removed your League Admin role.", ""),
        ]
        # subTest each, in this order on self.alex; assert the newest Notification for alex
    def test_only_the_target_is_notified(self): ...
    def test_muted_sends_nothing(self): ...   # with notifications.signals.muted()
    def test_double_grant_notifies_once(self): ...

@skipUnlessDBFeature("has_select_for_update")
class RoleLockTests(TestCase):
    def test_change_locks_the_group_row(self):
        with CaptureQueriesContext(connection) as ctx:
            change_role(self.boss, self.alex, SCOREKEEPER_ROLE, True)
        self.assertTrue(any("FOR UPDATE" in q["sql"] and "auth_group" in q["sql"]
                            for q in ctx.captured_queries))

@skipUnlessDBFeature("has_select_for_update")
class RoleRaceTests(TransactionTestCase):
    def test_two_admins_removing_each_other_leave_one(self):
        # a, b: League Admins. barrier = threading.Barrier(2).
        # each thread: barrier.wait(); try change_role(me, other, LEAGUE_ADMIN_ROLE, False)
        # record "ok" or the exception class name; finally connection.close()
        # join both; then:
        self.assertEqual(results.count("ok"), 1)
        self.assertIn(next(r for r in results if r != "ok"),
                      {"RoleChangeRefused", "PermissionDenied"})
        self.assertEqual(league_admin_count(), 1)
```

The loser raises `RoleChangeRefused` (count 1) or `PermissionDenied` (its own role is gone). Which one depends on timing, so the test accepts either.

- [ ] **Step 2: Run and see them fail**

Run: `python manage.py test accounts.test_role_admin.RoleNotificationTests`
Expected: FAIL, `Notification.DoesNotExist`. (The lock and race classes skip on SQLite.)

- [ ] **Step 3: Add the receiver**

Connect with `@receiver(role_changed, dispatch_uid="notify-role-changed")`. Import `role_changed` from `accounts.role_admin`. Build the verb with `display_name(actor)` and the role name. Links: `reverse("matches:mine")` for Scorekeeper added, `reverse("core:overview")` for League Admin added, `""` for removals.

- [ ] **Step 4: Run and see them pass**

Run: `python manage.py test accounts.test_role_admin notifications`
Expected: `OK`. If Postgres is available, also run `DATABASE_URL='postgres://USER:PASSWORD@localhost:5432/playnyu' python manage.py test accounts.test_role_admin`, and expect `OK` with no skips.

- [ ] **Step 5: Commit**

```bash
git add notifications/signals.py accounts/test_role_admin.py
git commit -m "#261: Notify users of role changes and test the role lock"
```

---

### Task 4: Roles list page

**Files:**
- Create: `accounts/role_views.py`, `accounts/templates/accounts/roles.html`, `accounts/test_role_views.py`
- Modify: `accounts/forms.py` (add `RoleFilterForm`), `accounts/role_admin.py` (add `role_rows`), `accounts/urls.py`, `docs/DESIGN.md`, `core/test_no_email_names.py`
- Maybe modify: `static/css/playnyu.css` (only if row buttons are under 40px at 375px)

**Interfaces:**
- Consumes: `listable_users`, `league_admin_count`, `can_manage_roles`, `MANAGED_ROLES` (Task 2).
- Produces:
  - `RoleFilterForm(data)`, with `auto_id="roles_%s"`. `q = CharField(required=False, max_length=100, strip=True, label="Search")`. `role = ChoiceField(required=False, choices=[("", "All people"), ("scorekeeper", "Scorekeepers"), ("league_admin", "League Admins")])`. Method `filter(queryset) -> QuerySet` applies each field that cleaned. For `q`, each whitespace word must match `first_name`, `last_name` or `email` (`icontains`, `Q` OR inside a word, AND across words). For `role`, filter `is_scorekeeper=True` or `is_league_admin=True`.
  - `role_rows() -> QuerySet`: `listable_users()` annotated with `is_scorekeeper`, `is_league_admin` (`Exists` over `User.groups.through` with `group__name`), `unscored_matches` (`Coalesce(Subquery(...count...), 0)` over `Match.objects.unscored()`), and ordered `first_name, last_name, email, pk`.
  - URL `accounts:roles` → `role_list`, path `roles/`.
  - `ROLES_PER_PAGE = 20` in `accounts/role_views.py`.
  - Context: `filter_form`, `page_obj`, `querystring` (the cleaned `q` and `role` only, urlencoded), `league_admin_count`, `nav_section="league_setup"`.
  - Template POST forms (Task 5 reads them) post to `accounts:change_role user.pk` with hidden `role` (`scorekeeper`/`league_admin`), `action` (`add`/`remove`), `q`, `role_filter`, `page`.

- [ ] **Step 1: Write the failing tests** in `accounts/test_role_views.py`.

```python
class RoleListAccessTests(TestCase):
    def test_anonymous_goes_to_login(self): ...          # 302, "/accounts/login/" in Location
    def test_casual_player_and_scorekeeper_get_403(self): ...   # subTest for each
    def test_league_admin_and_superuser_get_200(self): ...
    def test_league_setup_is_highlighted(self):
        self.assertEqual(response.context["nav_section"], "league_setup")

class RoleListContentTests(TestCase):
    def test_placeholder_and_inactive_users_are_not_listed(self): ...
    def test_search_matches_first_last_full_name_and_email(self): ...  # subTest: "alex", "lee", "alex lee", "alex@nyu"
    def test_role_filter_shows_holders_only(self): ...
    def test_bad_role_value_is_ignored(self): ...          # ?role=bogus -> 200, everyone listed
    def test_long_query_is_ignored(self): ...              # q of 200 chars -> 200, unfiltered
    def test_pages_keep_the_filters(self):
        # 21 matching users; ?q=player&role=&page=1 -> context page_obj.paginator.num_pages == 2
        self.assertContains(response, "?q=player&amp;page=2")
    def test_out_of_range_page_gives_the_last_page(self): ...  # ?page=999 -> 200
    def test_email_is_labelled(self):
        self.assertContains(response, '<span class="visually-hidden">Email: </span>alex@nyu.edu', html=False)
    def test_own_and_last_league_admin_remove_is_disabled(self): ...
        # boss is the only League Admin and the viewer: the button has `disabled`
        # and the reason "You can't remove your own League Admin role"
    def test_last_league_admin_reason_for_another_viewer(self): ...
        # root views; boss is the only holder -> "The league needs at least one League Admin"
    def test_superuser_row_has_site_admin_badge(self): ...
    def test_unscored_count_and_needs_reassigning_badge(self): ...
        # alex: Scorekeeper with 2 unscored -> "Assigned to 2 unscored matches", no badge
        # sam: no role, 1 unscored -> "Assigned to 1 unscored match" and "Needs reassigning"
    def test_empty_state(self): ...   # ?q=zzz -> "No one matches these filters." and "Clear filters"
    def test_query_count_does_not_grow_with_rows(self):
        counts = []
        for total in (2, 20):
            # make `total` users with roles and an unscored match each, then:
            with CaptureQueriesContext(connection) as ctx:
                self.client.get(reverse("accounts:roles"))
            counts.append(len(ctx))
        self.assertEqual(counts[0], counts[1])
```

In `core/test_no_email_names.py` `NamelessPageTests`, add:

```python
def test_roles_page_labels_the_email(self):
    self.client.force_login(self.admin)
    response = self.client.get(reverse("accounts:roles"))
    self.assertContains(response, FALLBACK_NAME)
    self.assertContains(response, f'<span class="visually-hidden">Email: </span>{NAMELESS_EMAIL}', count=1)
```

- [ ] **Step 2: Run and see them fail**

Run: `python manage.py test accounts.test_role_views core.test_no_email_names`
Expected: `NoReverseMatch: 'roles' is not a valid view function or pattern name`

- [ ] **Step 3: Implement the form, `role_rows`, the view, the URL and the template**

The view: `@login_required`, then `if not can_manage_roles(request.user): raise PermissionDenied`. Then `form = RoleFilterForm(request.GET)`, `form.filter(role_rows())`, `Paginator(...).get_page(request.GET.get("page"))`. Build `querystring` from `form.cleaned_data` (only non-empty `q` and `role`), not from raw GET, so a bad value drops out of the links.

The template follows the spec sketches and the "Markup rules" list: page header (`subheader` "League Admin", `<h1>Roles</h1>`, meta "Who keeps score and who runs the league.", "League setup" `btn-outline-secondary`), `col-lg-8` People card (the filter form in `card-body`, the count in `card-actions` "N people", `list-group list-group-flush` rows, `components/pager.html` with `label="People pages"`), `col-lg-4` "About roles" card. The disabled reason uses `{% if row.pk == user.pk %}` first, then `{% elif row.is_league_admin and league_admin_count <= 1 %}`. The Remove League Admin button is disabled only when `row.is_league_admin` is true and one of those two cases applies.

At 375px, check that the row buttons are at least 40px tall. If not, add `.pn-roles .btn-sm { min-height: 2.5rem; }` inside `@media (max-width: 767.98px)` under a `/* Roles page */` comment, and put `pn-roles` on the list group. Add `pn-roles` to the DESIGN.md §9 class list.

`docs/DESIGN.md`:
- §5 "Person names": after "Show an email only where the email is the point of the field", add: "The roles page is one: it shows the email after a visually-hidden 'Email:' label, so League Admins can tell accounts apart."
- §6: add a "Roles (League Admin)" row: page header with League setup (outline) → `col-lg-8` People card: GET filter (Search, Role), count in `card-actions`, list rows (avatar `sm`, `display_name`, role badges `bg-primary-lt`, `Site admin` `bg-secondary-lt`, `Needs reassigning` `bg-yellow-lt`, email and unscored count below, one POST form per action: Add `btn-sm btn-outline-secondary`, Remove `btn-sm btn-ghost-danger`, disabled with the reason), own row `pn-row-me`, pager → `col-lg-4` About roles card. No `btn-primary`.

- [ ] **Step 4: Run and see them pass**

Run: `python manage.py test accounts core`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add accounts/ core/test_no_email_names.py docs/DESIGN.md static/css/playnyu.css
git commit -m "#261: Add the League Admin roles page with search, role filter and paging"
```

---

### Task 5: Change a role (POST)

**Files:**
- Modify: `accounts/role_views.py` (add `change_role` view), `accounts/urls.py`
- Test: `accounts/test_role_views.py` (add `ChangeRoleViewTests`)

**Interfaces:**
- Consumes: `change_role` service, `RoleChangeRefused`, `MANAGED_ROLES`, `listable_users`, `unscored_match_count` (Task 2). The hidden fields from Task 4.
- Produces: URL `accounts:change_role` → `role_views.change_role`, path `roles/<int:user_pk>/`. Import the service as `from . import role_admin`, so the view name doesn't shadow it.

- [ ] **Step 1: Write the failing tests**

```python
class ChangeRoleViewTests(TestCase):
    def post(self, user, **data):
        defaults = {"role": "scorekeeper", "action": "add"}
        return self.client.post(reverse("accounts:change_role", args=[user.pk]), {**defaults, **data})

    def test_get_is_405(self): ...
    def test_casual_player_gets_403_and_nothing_changes(self): ...
    def test_csrf_is_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.boss)
        response = client.post(reverse("accounts:change_role", args=[self.alex.pk]), {"role": "scorekeeper", "action": "add"})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(has_role(self.alex, SCOREKEEPER_ROLE))
    def test_placeholder_and_inactive_targets_are_404(self): ...
    def test_bad_role_or_action_is_400(self): ...   # subTest: role=casual_player, role=, action=toggle
    def test_add_redirects_back_with_filters_and_page(self):
        response = self.post(self.alex, q="lee", role_filter="scorekeeper", page="3")
        self.assertRedirects(response, reverse("accounts:roles") + "?q=lee&role=scorekeeper&page=3",
                             fetch_redirect_response=False)
    def test_bad_return_values_are_dropped(self): ...   # role_filter=bogus, page=abc -> plain accounts:roles
    def test_success_message(self): ...    # "Alex Lee is now a Scorekeeper."
    def test_double_post_logs_once(self): ...   # second: info "Alex Lee is already a Scorekeeper."; 1 AuditLog
    def test_refusals_show_error_messages(self): ...   # self and last copy, exact text
    def test_scorekeeper_removal_warns_about_unscored_matches(self):
        # alex: Scorekeeper with 3 unscored matches; remove -> warning
        # "Alex Lee still has 3 unscored matches and can't score them now. Choose another scorekeeper on Manage matches."
```

- [ ] **Step 2: Run and see them fail**

Run: `python manage.py test accounts.test_role_views.ChangeRoleViewTests`
Expected: `NoReverseMatch: 'change_role'`

- [ ] **Step 3: Implement the view**

`@login_required @require_POST`. Check `can_manage_roles` (403). Then `get_object_or_404(listable_users(), pk=user_pk)`. Look up `MANAGED_ROLES.get(request.POST.get("role"))` and check `action in ("add", "remove")`; return `HttpResponseBadRequest` otherwise. Call the service and map the result to `messages.success` / `messages.info` / `messages.error` (on `RoleChangeRefused`, `str(error)`) / `messages.warning` (after a Scorekeeper removal with `unscored_match_count > 0`, pluralize "match"/"matches"). Build the redirect from `RoleFilterForm({"q": POST q, "role": POST role_filter})`, using the cleaned values only, plus `page` when it is all digits. Use the order `q`, `role`, `page`.

- [ ] **Step 4: Run and see them pass**

Run: `python manage.py test accounts`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add accounts/role_views.py accounts/urls.py accounts/test_role_views.py
git commit -m "#261: Grant and remove roles from the roles page with POST and CSRF"
```

---

### Task 6: Entry points

**Files:**
- Modify: `teams/views.py` (`league_setup` counts only), `teams/templates/teams/league_setup.html`, `core/templates/core/overview.html`, `matches/forms.py` (`MatchForm.__init__`, scorekeeper help text)
- Test: `accounts/test_role_views.py` (add `EntryPointTests`)

Keep the `teams/views.py` change to the two new keys in `league_setup`'s `counts` dict, so it doesn't conflict with #262.

**Interfaces:**
- Consumes: `accounts:roles` (Task 4), `league_admin_count` (Task 2), `users_with_role`.
- Produces: `counts["league_admins"]` (from `league_admin_count()`) and `counts["scorekeepers"]` (`listable_users().filter(groups__name=SCOREKEEPER_ROLE).distinct().count()`) in `league_setup`.

- [ ] **Step 1: Write the failing tests**

```python
class EntryPointTests(TestCase):
    def test_league_setup_links_roles_with_counts(self):
        response = self.client.get(reverse("teams:league_setup"))
        self.assertContains(response, f'href="{reverse("accounts:roles")}"')
        self.assertContains(response, "1 League Admin · 0 Scorekeepers")  # exact text
    def test_overview_quick_links_roles(self): ...
    def test_overview_shows_role_change_in_recent_changes(self):
        role_admin.change_role(self.boss, self.alex, SCOREKEEPER_ROLE, True)
        self.assertContains(self.client.get(reverse("core:overview")), "Granted role")
        self.assertContains(..., "Scorekeeper to Alex Lee")
    def test_match_form_hint_with_no_scorekeepers(self):
        help_text = MatchForm(season=self.season).fields["scorekeeper"].help_text
        self.assertIn("No one has the Scorekeeper role yet.", help_text)
        self.assertIn(f'href="{reverse("accounts:roles")}"', help_text)
        self.assertIn("Grant the role", help_text)
    def test_match_form_hint_with_scorekeepers(self): ...  # "Only Scorekeepers are listed." and "Manage roles"
```

- [ ] **Step 2: Run and see them fail**

Run: `python manage.py test accounts.test_role_views.EntryPointTests`
Expected: FAIL on the missing link and help text.

- [ ] **Step 3: Implement**

- League setup: a seventh card, after Facilities, in the same markup. Use icon `ti-shield-check`, link text "Roles", and the meta line `{{ counts.league_admins }} League Admin{{ counts.league_admins|pluralize }} · {{ counts.scorekeepers }} Scorekeeper{{ counts.scorekeepers|pluralize }}` with `pn-num` on the numbers. Change the page-meta to "Configure seasons, sports, event types, divisions, free-agent placement, matches, facilities and roles."
- Overview: a "Roles" quick link (`ti-shield-check`) after "Moderation queue". Change the Recent changes empty subtitle to "Changes to teams, seasons, sports, matches, facilities and roles show up here."
- `MatchForm.__init__`: after the scorekeeper queryset is set, set `help_text` with `format_html`. With an empty queryset: `'No one has the Scorekeeper role yet. <a href="{}">Grant the role</a>'`. Otherwise: `'Only Scorekeepers are listed. <a href="{}">Manage roles</a>'`. Both use `reverse("accounts:roles")`.

- [ ] **Step 4: Run and see them pass**

Run: `python manage.py test accounts teams.test_league_setup core matches`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add teams/views.py teams/templates/teams/league_setup.html core/templates/core/overview.html matches/forms.py accounts/test_role_views.py
git commit -m "#261: Link the roles page from League setup, the overview and the match form"
```

---

### Task 7: Permission sweep and final checks

**Files:**
- Test: `accounts/test_role_views.py` (add `RolesPermSweepTests`, like `teams/test_perm_sweep_teams.py`)

- [ ] **Step 1: Add the sweep test.** For `accounts:roles` (GET) and `accounts:change_role` (POST): anonymous 302 to login, Casual Player 403, League Admin 200 for GET and 302 for POST.

- [ ] **Step 2: Run the CI commands**

```bash
black --check .
flake8 .
coverage run manage.py test
coverage report --fail-under=80
python manage.py makemigrations --check --dry-run
```

Expected: black "would be left unchanged", flake8 prints nothing, tests `OK`, coverage at least 80%, `No changes detected`.

- [ ] **Step 3: Check the page by hand** at 1280px and 375px (`python manage.py runserver`, signed in as a League Admin). Expected: no horizontal scroll, row buttons wrap under the name, the disabled reasons show on hover, and no label in the navbar wraps.

- [ ] **Step 4: Commit**

```bash
git add accounts/test_role_views.py
git commit -m "#261: Add the roles page permission sweep"
```

---

## Changes during the build

- Commits: Tasks 2 and 3 are one commit. Tasks 4 and 5 are one commit, because the list template posts to `accounts:change_role`. The Task 7 sweep is in the Task 6 commit.
- Task 2: `role_rows` is in the Task 2 commit, with the rest of the service.
- Task 3: Docker was not running, so the Postgres lock and race tests skipped locally.
- Task 4: each button is the partial `accounts/templates/accounts/_role_button.html`.
- Task 4: `RoleFilterForm.cleaned()` returns the valid, non-empty `q` and `role`. The list view and the POST redirect both use it.
- Task 4: a row is `d-flex flex-column flex-md-row align-items-md-center gap-3`, with the avatar and name in one inner group. With `flex-wrap`, the buttons always wrapped under the name at 1280px.
- Task 4: the "About roles" card has a fourth rule: a Scorekeeper who loses the role keeps their matches.
- Task 4: `.pn-roles .btn-sm { min-height: 2.5rem; }` below 768px. Tabler's `btn-sm` is under 40px.
- Task 4: tests match the rendered `pn-num` spans, for example `<span class="pn-num">21</span> people`.
- Task 5: the test helper follows each redirect to read the messages, so the messages of one post do not stay for the next post.
- Task 6: the match form hint checks `users_with_role(SCOREKEEPER_ROLE)`. A kept former scorekeeper does not count as a Scorekeeper.
- Task 6: `teams/test_league_setup.py` expects the two new `counts` keys.
