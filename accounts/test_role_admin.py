"""The role change service (#261): rules, audit rows, notifications, the lock."""

import datetime
import threading

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.placeholders import placeholder_for
from accounts.role_admin import (
    RoleChangeRefused,
    change_role,
    league_admin_count,
    unscored_match_count,
)
from accounts.roles import (
    CASUAL_PLAYER_ROLE,
    LEAGUE_ADMIN_ROLE,
    SCOREKEEPER_ROLE,
    assign_role,
    has_role,
)
from audit.models import AuditLog
from facilities.models import Facility
from matches.models import Match
from notifications.models import Notification
from notifications.signals import muted
from teams.models import Season, Sport, Team
from teams.season_rules import SeasonState


def make_user(email, first="", last="", role=None, **extra):
    # Real accounts use the email as the username (accounts/forms.py).
    user = get_user_model().objects.create_user(
        username=email,
        email=email,
        password="pass12345!",
        first_name=first,
        last_name=last,
        **extra,
    )
    if role:
        assign_role(user, role)
    return user


def make_superuser(email="root@nyu.edu"):
    return get_user_model().objects.create_superuser(
        username=email, email=email, password="pass12345!"
    )


def role_rows():
    return AuditLog.objects.filter(object_type="Role")


class RoleFixtures(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.boss = make_user("boss@nyu.edu", "Lee", "Admin", role=LEAGUE_ADMIN_ROLE)
        cls.alex = make_user("alex@nyu.edu", "Alex", "Lee")
        cls.nameless = make_user("nameless@nyu.edu")
        cls.ghost, _ = placeholder_for("ghost@nyu.edu")
        cls.root = make_superuser()

    @classmethod
    def make_match(
        cls,
        scorekeeper,
        state=SeasonState.ACTIVE,
        status=Match.Status.SCHEDULED,
        scored=False,
        days=2,
    ):
        sport, _ = Sport.objects.get_or_create(name="Soccer")
        season = Season.objects.create(
            name=f"Season {Season.objects.count()}",
            start_date=datetime.date(2026, 9, 1),
            state=state,
        )
        home, away = (
            Team.objects.create(name=name, sport=sport, season=season, captain=cls.boss)
            for name in (f"Home {season.pk}", f"Away {season.pk}")
        )
        facility, _ = Facility.objects.get_or_create(
            name="Pier 40", source=Facility.Source.NYU
        )
        starts_at = timezone.now() + datetime.timedelta(days=days)
        return Match.objects.create(
            season=season,
            home_team=home,
            away_team=away,
            facility=facility,
            starts_at=starts_at,
            ends_at=starts_at + datetime.timedelta(hours=2),
            status=status,
            home_score=2 if scored else None,
            away_score=1 if scored else None,
            scorekeeper=scorekeeper,
        )


class ChangeRoleTests(RoleFixtures):
    def test_grant_scorekeeper_adds_group_and_audit_row(self):
        self.assertTrue(change_role(self.boss, self.alex, SCOREKEEPER_ROLE, True))
        self.assertTrue(has_role(self.alex, SCOREKEEPER_ROLE))
        row = role_rows().get()
        self.assertEqual(
            (row.actor, row.action, row.object_id, row.object_repr),
            (self.boss, "granted", str(self.alex.pk), "Scorekeeper to Alex Lee"),
        )

    def test_remove_writes_removed_row(self):
        assign_role(self.alex, SCOREKEEPER_ROLE)
        self.assertTrue(change_role(self.boss, self.alex, SCOREKEEPER_ROLE, False))
        self.assertFalse(has_role(self.alex, SCOREKEEPER_ROLE))
        row = role_rows().get()
        self.assertEqual(
            (row.action, row.object_repr), ("removed", "Scorekeeper from Alex Lee")
        )

    def test_league_admin_rows(self):
        change_role(self.boss, self.alex, LEAGUE_ADMIN_ROLE, True)
        change_role(self.boss, self.alex, LEAGUE_ADMIN_ROLE, False)
        self.assertEqual(
            list(role_rows().order_by("pk").values_list("action", "object_repr")),
            [
                ("granted", "League Admin to Alex Lee"),
                ("removed", "League Admin from Alex Lee"),
            ],
        )

    def test_second_grant_changes_nothing(self):
        change_role(self.boss, self.alex, SCOREKEEPER_ROLE, True)
        self.assertFalse(change_role(self.boss, self.alex, SCOREKEEPER_ROLE, True))
        self.assertEqual(role_rows().count(), 1)

    def test_removing_a_missing_role_changes_nothing(self):
        self.assertFalse(change_role(self.boss, self.alex, SCOREKEEPER_ROLE, False))
        self.assertFalse(role_rows().exists())

    def test_nameless_target_uses_fallback_name(self):
        change_role(self.boss, self.nameless, SCOREKEEPER_ROLE, True)
        self.assertEqual(role_rows().get().object_repr, "Scorekeeper to PlayNYU player")

    def test_casual_player_is_rejected(self):
        with self.assertRaises(ValueError):
            change_role(self.boss, self.alex, CASUAL_PLAYER_ROLE, True)
        self.assertFalse(role_rows().exists())

    def test_actor_without_access_is_denied(self):
        with self.assertRaises(PermissionDenied):
            change_role(self.alex, self.nameless, SCOREKEEPER_ROLE, True)
        self.assertFalse(has_role(self.nameless, SCOREKEEPER_ROLE))

    def test_superuser_without_the_group_can_change_roles(self):
        self.assertTrue(change_role(self.root, self.alex, SCOREKEEPER_ROLE, True))


class LeagueAdminRuleTests(RoleFixtures):
    def test_self_removal_is_refused(self):
        assign_role(self.alex, LEAGUE_ADMIN_ROLE)  # two holders: only the self rule
        with self.assertRaisesMessage(
            RoleChangeRefused,
            "You can't remove your own League Admin role. Ask another League Admin.",
        ):
            change_role(self.boss, self.boss, LEAGUE_ADMIN_ROLE, False)
        self.assertTrue(has_role(self.boss, LEAGUE_ADMIN_ROLE))

    def test_superuser_self_removal_is_refused(self):
        assign_role(self.root, LEAGUE_ADMIN_ROLE)
        with self.assertRaises(RoleChangeRefused):
            change_role(self.root, self.root, LEAGUE_ADMIN_ROLE, False)
        self.assertTrue(has_role(self.root, LEAGUE_ADMIN_ROLE))

    def test_last_admin_is_refused_even_for_a_superuser(self):
        with self.assertRaisesMessage(
            RoleChangeRefused,
            "Lee Admin is the last League Admin. Make someone else a League Admin first.",
        ):
            change_role(self.root, self.boss, LEAGUE_ADMIN_ROLE, False)
        self.assertTrue(has_role(self.boss, LEAGUE_ADMIN_ROLE))
        self.assertFalse(role_rows().exists())

    def test_inactive_and_placeholder_holders_do_not_count(self):
        assign_role(self.ghost, LEAGUE_ADMIN_ROLE)
        make_user("gone@nyu.edu", "Gone", "User", LEAGUE_ADMIN_ROLE, is_active=False)
        self.assertEqual(league_admin_count(), 1)
        with self.assertRaises(RoleChangeRefused):
            change_role(self.root, self.boss, LEAGUE_ADMIN_ROLE, False)

    def test_superuser_holding_the_group_counts(self):
        assign_role(self.root, LEAGUE_ADMIN_ROLE)
        self.assertTrue(change_role(self.root, self.boss, LEAGUE_ADMIN_ROLE, False))
        self.assertEqual(league_admin_count(), 1)

    def test_league_admin_count(self):
        self.assertEqual(league_admin_count(), 1)


class ScorekeeperMatchTests(RoleFixtures):
    def test_removal_keeps_the_assignment(self):
        assign_role(self.alex, SCOREKEEPER_ROLE)
        match = self.make_match(scorekeeper=self.alex)
        change_role(self.boss, self.alex, SCOREKEEPER_ROLE, False)
        match.refresh_from_db()
        self.assertEqual(match.scorekeeper, self.alex)
        self.assertEqual(unscored_match_count(self.alex), 1)

    def test_unscored_counts_live_unscored_scheduled_only(self):
        left_out = {
            "cancelled": {"status": Match.Status.CANCELLED},
            "scored": {"scored": True},
            "draft season": {"state": SeasonState.DRAFT},
            "closed season": {"state": SeasonState.CLOSED},
        }
        for label, options in left_out.items():
            with self.subTest(label):
                match = self.make_match(self.alex, **options)
                self.assertEqual(unscored_match_count(self.alex), 0)
                match.delete()
        # A past, ended, unscored match in an active season still counts.
        self.make_match(self.alex, days=-3)
        self.make_match(self.alex, state=SeasonState.OPEN)
        self.assertEqual(unscored_match_count(self.alex), 2)
        self.assertEqual(unscored_match_count(self.nameless), 0)


class RoleNotificationTests(RoleFixtures):
    def newest_for(self, user):
        return Notification.objects.filter(recipient=user).first()

    def test_each_change_sends_its_verb_and_link(self):
        cases = [
            (
                SCOREKEEPER_ROLE,
                True,
                "Lee Admin made you a Scorekeeper. Your matches are on My matches.",
                reverse("matches:mine"),
            ),
            (
                LEAGUE_ADMIN_ROLE,
                True,
                "Lee Admin made you a League Admin.",
                reverse("core:overview"),
            ),
            (SCOREKEEPER_ROLE, False, "Lee Admin removed your Scorekeeper role.", ""),
            (LEAGUE_ADMIN_ROLE, False, "Lee Admin removed your League Admin role.", ""),
        ]
        for count, (role, grant, verb, link) in enumerate(cases, start=1):
            with self.subTest(role=role, grant=grant):
                change_role(self.boss, self.alex, role, grant)
                note = self.newest_for(self.alex)
                self.assertEqual((note.verb, note.link), (verb, link))
                self.assertEqual(
                    Notification.objects.filter(recipient=self.alex).count(), count
                )

    def test_nameless_actor_uses_fallback_name(self):
        assign_role(self.nameless, LEAGUE_ADMIN_ROLE)
        change_role(self.nameless, self.alex, LEAGUE_ADMIN_ROLE, True)
        self.assertEqual(
            self.newest_for(self.alex).verb, "PlayNYU player made you a League Admin."
        )

    def test_only_the_target_is_notified(self):
        assign_role(self.root, LEAGUE_ADMIN_ROLE)
        change_role(self.boss, self.alex, LEAGUE_ADMIN_ROLE, True)
        self.assertEqual(
            list(Notification.objects.values_list("recipient", flat=True)),
            [self.alex.pk],
        )

    def test_muted_sends_nothing(self):
        with muted():
            change_role(self.boss, self.alex, SCOREKEEPER_ROLE, True)
        self.assertFalse(Notification.objects.exists())
        self.assertEqual(role_rows().count(), 1)

    def test_double_grant_notifies_once(self):
        change_role(self.boss, self.alex, SCOREKEEPER_ROLE, True)
        change_role(self.boss, self.alex, SCOREKEEPER_ROLE, True)
        self.assertEqual(Notification.objects.filter(recipient=self.alex).count(), 1)

    def test_refused_change_notifies_nobody(self):
        with self.assertRaises(RoleChangeRefused):
            change_role(self.root, self.boss, LEAGUE_ADMIN_ROLE, False)
        self.assertFalse(Notification.objects.exists())


@skipUnlessDBFeature("has_select_for_update")
class RoleLockTests(RoleFixtures):
    def test_change_locks_the_group_row(self):
        with CaptureQueriesContext(connection) as ctx:
            change_role(self.boss, self.alex, SCOREKEEPER_ROLE, True)
        self.assertTrue(
            any(
                "FOR UPDATE" in q["sql"] and "auth_group" in q["sql"]
                for q in ctx.captured_queries
            )
        )


@skipUnlessDBFeature("has_select_for_update")
class RoleRaceTests(TransactionTestCase):
    def test_two_admins_removing_each_other_leave_one(self):
        a = make_user("a@nyu.edu", "Ann", "A", role=LEAGUE_ADMIN_ROLE)
        b = make_user("b@nyu.edu", "Ben", "B", role=LEAGUE_ADMIN_ROLE)
        barrier = threading.Barrier(2)
        results = []

        def remove(me, other):
            try:
                barrier.wait()
                change_role(me, other, LEAGUE_ADMIN_ROLE, False)
                results.append("ok")
            except Exception as error:  # noqa: BLE001 - the test records any failure
                results.append(type(error).__name__)
            finally:
                connection.close()

        threads = [
            threading.Thread(target=remove, args=(a, b)),
            threading.Thread(target=remove, args=(b, a)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(results.count("ok"), 1, results)
        self.assertIn(
            next(r for r in results if r != "ok"),
            {"RoleChangeRefused", "PermissionDenied"},
        )
        self.assertEqual(league_admin_count(), 1)
