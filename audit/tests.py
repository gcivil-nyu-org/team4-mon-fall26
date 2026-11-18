import threading
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.roles import LEAGUE_ADMIN_ROLE, assign_role
from audit.models import AuditLog
from audit.signals import is_muted, muted
from facilities.models import Facility
from matches.models import Match
from teams.models import Season, Sport, Team


def make_admin(email="admin@nyu.edu"):
    user = get_user_model().objects.create_user(
        username=email, email=email, password="testpass123"
    )
    assign_role(user, LEAGUE_ADMIN_ROLE)
    return user


def logs_for(object_type, object_id):
    return AuditLog.objects.filter(object_type=object_type, object_id=str(object_id))


class AuditSignalTests(TestCase):
    def test_create_update_delete_are_logged(self):
        sport = Sport.objects.create(name="Soccer")
        entry = logs_for("Sport", sport.pk).get()
        self.assertEqual(entry.action, "created")
        self.assertIsNone(entry.actor)
        self.assertEqual(entry.object_repr, "Soccer")

        sport.name = "Soccer Club"
        sport.save()
        entry = logs_for("Sport", sport.pk).latest("pk")
        self.assertEqual(entry.action, "updated")

        pk = sport.pk
        sport.delete()
        entry = logs_for("Sport", pk).latest("pk")
        self.assertEqual(entry.action, "deleted")

    def test_each_watched_model_logs_its_type_and_id(self):
        admin = make_admin()
        season = Season.objects.create(
            name="Fall 2026", start_date=date(2026, 9, 1), state="open"
        )
        sport = Sport.objects.create(name="Basketball")
        facility = Facility.objects.create(name="Gym", source=Facility.Source.NYU)
        team = Team.objects.create(
            name="Violets", sport=sport, season=season, captain=admin
        )
        rival = Team.objects.create(
            name="Rivals", sport=sport, season=season, captain=admin
        )
        now = timezone.now()
        match = Match.objects.create(
            season=season,
            home_team=team,
            away_team=rival,
            facility=facility,
            starts_at=now,
            ends_at=now + timedelta(hours=2),
        )
        for instance, object_type in (
            (season, "Season"),
            (sport, "Sport"),
            (facility, "Facility"),
            (team, "Team"),
            (match, "Match"),
        ):
            entry = logs_for(object_type, instance.pk).get()
            self.assertEqual(entry.action, "created")
            self.assertEqual(entry.object_repr, str(instance)[:200])

    def test_web_change_is_attributed_to_the_signed_in_admin(self):
        admin = make_admin()
        self.client.force_login(admin)
        response = self.client.post(
            reverse("teams:manage_sports"), {"name": "Volleyball"}
        )
        self.assertEqual(response.status_code, 302)
        sport = Sport.objects.get(name="Volleyball")
        entry = logs_for("Sport", sport.pk).get()
        self.assertEqual(entry.action, "created")
        self.assertEqual(entry.actor, admin)


class MutedTests(TestCase):
    def test_nothing_is_logged_inside_the_block(self):
        with muted():
            sport = Sport.objects.create(name="Soccer")
            sport.name = "Soccer Club"
            sport.save()
            sport.delete()
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_saves_outside_the_block_are_still_logged(self):
        with muted():
            pass
        self.assertFalse(is_muted())
        Sport.objects.create(name="Soccer")
        self.assertEqual(AuditLog.objects.count(), 1)

    def test_mute_ends_after_an_exception(self):
        with self.assertRaises(ValueError):
            with muted():
                raise ValueError("boom")
        self.assertFalse(is_muted())
        Sport.objects.create(name="Soccer")
        self.assertEqual(AuditLog.objects.count(), 1)

    def test_nested_blocks_stay_muted_until_the_outer_one_ends(self):
        with muted():
            with muted():
                pass
            self.assertTrue(is_muted())
        self.assertFalse(is_muted())

    def test_mute_does_not_reach_another_thread(self):
        seen = []
        with muted():
            thread = threading.Thread(target=lambda: seen.append(is_muted()))
            thread.start()
            thread.join()
        self.assertEqual(seen, [False])


class RoleActionTests(TestCase):
    def test_role_actions_exist(self):
        self.assertEqual(AuditLog.Action.GRANTED, "granted")
        self.assertEqual(AuditLog.Action.GRANTED.label, "Granted")
        self.assertEqual(AuditLog.Action.REMOVED, "removed")
        self.assertEqual(AuditLog.Action.REMOVED.label, "Removed")

    def test_role_row_saves(self):
        row = AuditLog.objects.create(
            action=AuditLog.Action.GRANTED,
            object_type="Role",
            object_id="7",
            object_repr="Scorekeeper to Alex Lee",
        )
        self.assertEqual(row.get_action_display(), "Granted")
