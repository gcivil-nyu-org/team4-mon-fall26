import datetime
import unittest
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from facilities.models import Facility
from matches.models import Match
from teams.models import Roster, Season, Sport, Team
from teams.season_rules import SeasonState

from .models import Notification
from .signals import score_recorded

NY = ZoneInfo("America/New_York")


def make_user(username):
    return get_user_model().objects.create_user(
        username=username, email=f"{username}@nyu.edu", password="pass12345!"
    )


class NotificationFixtures(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = make_user("nalice")
        cls.bob = make_user("nbob")
        cls.cara = make_user("ncara")
        cls.outsider = make_user("noutsider")
        cls.home_captain = make_user("ncaphome")
        cls.away_captain = make_user("ncapaway")
        cls.sport = Sport.objects.create(name="NSoccer")
        cls.season = Season.objects.create(
            name="N Fall",
            start_date=datetime.date(2026, 9, 1),
            state=SeasonState.OPEN,
        )
        cls.home = Team.objects.create(
            name="NViolets",
            sport=cls.sport,
            season=cls.season,
            captain=cls.home_captain,
        )
        cls.away = Team.objects.create(
            name="NBobcats",
            sport=cls.sport,
            season=cls.season,
            captain=cls.away_captain,
        )
        Roster.objects.create(team=cls.home, player=cls.alice)
        Roster.objects.create(team=cls.away, player=cls.bob)
        cls.field = Facility.objects.create(name="NPier 40", source=Facility.Source.NYU)

    def setUp(self):
        # Roster/match signals fire during setup; each test starts clean.
        Notification.objects.all().delete()

    def make_match(self, **overrides):
        values = dict(
            season=self.season,
            home_team=self.home,
            away_team=self.away,
            facility=self.field,
            starts_at=datetime.datetime(2026, 11, 10, 18, 0, tzinfo=NY),
            ends_at=datetime.datetime(2026, 11, 10, 20, 0, tzinfo=NY),
        )
        values.update(overrides)
        return Match.objects.create(**values)

    def verbs_for(self, user):
        return list(
            Notification.objects.filter(recipient=user).values_list("verb", flat=True)
        )


class MatchScheduledTests(NotificationFixtures):
    def test_scheduled_match_notifies_both_teams(self):
        self.make_match()
        link = reverse("matches:season_schedule", args=[self.season.pk])
        for user in (
            self.alice,
            self.bob,
            self.home_captain,
            self.away_captain,
        ):
            notes = Notification.objects.filter(recipient=user)
            self.assertEqual(notes.count(), 1)
            self.assertIn("NViolets", notes[0].verb)
            self.assertIn("NBobcats", notes[0].verb)
            self.assertEqual(notes[0].link, link)
            self.assertFalse(notes[0].is_read)
        self.assertEqual(
            Notification.objects.filter(recipient=self.outsider).count(), 0
        )

    def test_resaving_a_match_without_a_score_notifies_nobody(self):
        match = self.make_match()
        Notification.objects.all().delete()
        match.save()
        self.assertEqual(Notification.objects.count(), 0)


class ScoreRecordedTests(NotificationFixtures):
    def test_score_signal_notifies_both_teams(self):
        match = self.make_match()
        Notification.objects.all().delete()
        score_recorded.send(sender=Match, match=match, home_score=2, away_score=1)
        for user in (self.alice, self.bob):
            verbs = self.verbs_for(user)
            self.assertEqual(len(verbs), 1)
            self.assertIn("2", verbs[0])
            self.assertIn("1", verbs[0])
        self.assertEqual(
            Notification.objects.filter(recipient=self.outsider).count(), 0
        )

    def test_score_signal_without_scores_still_notifies(self):
        match = self.make_match()
        Notification.objects.all().delete()
        score_recorded.send(sender=Match, match=match)
        self.assertIn("Score recorded", self.verbs_for(self.alice)[0])
        self.assertEqual(len(self.verbs_for(self.bob)), 1)

    def test_score_signal_without_match_notifies_nobody(self):
        score_recorded.send(sender=Match, match=None)
        self.assertEqual(Notification.objects.count(), 0)

    @unittest.skipUnless(
        hasattr(Match, "home_score"),
        "needs the matches score fields (sibling results work)",
    )
    def test_saving_scores_on_a_match_notifies_both_teams(self):
        match = self.make_match()
        Notification.objects.all().delete()
        match.home_score = 2
        match.away_score = 1
        match.save()
        for user in (self.alice, self.bob):
            verbs = self.verbs_for(user)
            self.assertEqual(len(verbs), 1)
            self.assertIn("Final score", verbs[0])
            self.assertIn("2", verbs[0])
        self.assertEqual(
            Notification.objects.filter(recipient=self.outsider).count(), 0
        )

    @unittest.skipUnless(
        hasattr(Match, "home_score"),
        "needs the matches score fields (sibling results work)",
    )
    def test_correcting_a_score_does_not_renotify(self):
        match = self.make_match(home_score=0, away_score=0)
        Notification.objects.all().delete()
        match.home_score = 3
        match.away_score = 2
        match.save()
        self.assertEqual(Notification.objects.count(), 0)


class RosterChangeTests(NotificationFixtures):
    def test_player_added_notifies_the_team(self):
        Roster.objects.create(team=self.home, player=self.cara)
        link = reverse("teams:detail", args=[self.home.pk])
        for user in (self.alice, self.cara, self.home_captain):
            notes = Notification.objects.filter(recipient=user)
            self.assertEqual(notes.count(), 1)
            self.assertIn("joined", notes[0].verb)
            self.assertIn("NViolets", notes[0].verb)
            self.assertEqual(notes[0].link, link)
        self.assertEqual(Notification.objects.filter(recipient=self.bob).count(), 0)

    def test_player_removed_notifies_remaining_and_removed(self):
        entry = Roster.objects.get(team=self.home, player=self.alice)
        entry.delete()
        for user in (self.alice, self.home_captain):
            notes = Notification.objects.filter(recipient=user)
            self.assertEqual(notes.count(), 1)
            self.assertIn("left", notes[0].verb)
        self.assertEqual(Notification.objects.filter(recipient=self.bob).count(), 0)
        self.assertEqual(
            Notification.objects.filter(recipient=self.outsider).count(), 0
        )


class NotificationVisibilityTests(NotificationFixtures):
    def test_only_the_recipient_sees_theirs(self):
        Notification.objects.create(recipient=self.alice, verb="Alice only", link="")
        Notification.objects.create(recipient=self.bob, verb="Bob only", link="")
        self.client.force_login(self.alice)
        response = self.client.get(reverse("notifications:list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alice only")
        self.assertNotContains(response, "Bob only")

    def test_login_required(self):
        response = self.client.get(reverse("notifications:list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_empty_state(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse("notifications:list"))
        self.assertContains(response, "No notifications yet")


class MarkReadTests(NotificationFixtures):
    def test_mark_single_read(self):
        note = Notification.objects.create(recipient=self.alice, verb="One", link="")
        other = Notification.objects.create(recipient=self.alice, verb="Two", link="")
        self.client.force_login(self.alice)
        response = self.client.post(reverse("notifications:mark_read", args=[note.pk]))
        self.assertRedirects(response, reverse("notifications:list"))
        note.refresh_from_db()
        other.refresh_from_db()
        self.assertTrue(note.is_read)
        self.assertFalse(other.is_read)

    def test_cannot_mark_someone_elses_notification(self):
        note = Notification.objects.create(recipient=self.bob, verb="Bob note", link="")
        self.client.force_login(self.alice)
        response = self.client.post(reverse("notifications:mark_read", args=[note.pk]))
        self.assertEqual(response.status_code, 404)
        note.refresh_from_db()
        self.assertFalse(note.is_read)

    def test_mark_read_requires_post(self):
        note = Notification.objects.create(recipient=self.alice, verb="One", link="")
        self.client.force_login(self.alice)
        response = self.client.get(reverse("notifications:mark_read", args=[note.pk]))
        self.assertEqual(response.status_code, 405)

    def test_mark_all_read(self):
        Notification.objects.create(recipient=self.alice, verb="One", link="")
        Notification.objects.create(recipient=self.alice, verb="Two", link="")
        Notification.objects.create(recipient=self.bob, verb="Bob", link="")
        self.client.force_login(self.alice)
        response = self.client.post(reverse("notifications:mark_all_read"))
        self.assertRedirects(response, reverse("notifications:list"))
        self.assertEqual(
            Notification.objects.filter(recipient=self.alice, is_read=False).count(),
            0,
        )
        bobs = Notification.objects.get(recipient=self.bob)
        self.assertFalse(bobs.is_read)


class NavbarCountTests(NotificationFixtures):
    def test_bell_shows_unread_count(self):
        Notification.objects.create(recipient=self.alice, verb="One", link="")
        self.client.force_login(self.alice)
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ti-bell")
        self.assertContains(response, reverse("notifications:list"))
        self.assertContains(response, "1 unread")

    def test_bell_has_no_count_when_all_read(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse("core:home"))
        self.assertContains(response, "ti-bell")
        self.assertNotContains(response, "unread")

    def test_no_bell_when_logged_out(self):
        response = self.client.get(reverse("core:home"))
        self.assertNotContains(response, "ti-bell")
