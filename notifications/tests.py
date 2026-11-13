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


class MatchCreatedWithScoresTests(NotificationFixtures):
    def test_match_created_with_scores_sends_only_new_match(self):
        """The seed path saves matches with scores on create."""
        self.make_match(home_score=2, away_score=1)
        for user in (self.alice, self.bob, self.home_captain, self.away_captain):
            verbs = self.verbs_for(user)
            self.assertEqual(len(verbs), 1)
            self.assertIn("New match scheduled", verbs[0])

    def test_match_created_cancelled_notifies_nobody(self):
        self.make_match(status=Match.Status.CANCELLED)
        self.assertEqual(Notification.objects.count(), 0)


class MatchChangeFixtures(NotificationFixtures):
    def setUp(self):
        super().setUp()
        self.match = self.make_match()
        Notification.objects.all().delete()
        self.members = (self.alice, self.bob, self.home_captain, self.away_captain)

    def assert_one_each(self, text):
        link = reverse("matches:season_schedule", args=[self.season.pk])
        for user in self.members:
            notes = Notification.objects.filter(recipient=user)
            self.assertEqual(notes.count(), 1)
            self.assertIn(text, notes[0].verb)
            self.assertEqual(notes[0].link, link)
        self.assertEqual(Notification.objects.count(), len(self.members))


class MatchRescheduledTests(MatchChangeFixtures):
    def test_time_change_notifies_both_rosters_once(self):
        self.match.starts_at = datetime.datetime(2026, 11, 14, 18, 0, tzinfo=NY)
        self.match.ends_at = datetime.datetime(2026, 11, 14, 20, 0, tzinfo=NY)
        self.match.save()
        self.assert_one_each(
            "Match rescheduled: NViolets vs NBobcats, Sat Nov 14 6:00 PM at NPier 40"
        )

    def test_end_time_change_alone_notifies(self):
        self.match.ends_at = datetime.datetime(2026, 11, 10, 21, 0, tzinfo=NY)
        self.match.save()
        self.assert_one_each("Match rescheduled")

    def test_facility_change_notifies_both_rosters_once(self):
        gym = Facility.objects.create(name="NPalladium", source=Facility.Source.NYU)
        self.match.facility = gym
        self.match.save()
        self.assert_one_each("Tue Nov 10 6:00 PM at NPalladium")

    def test_time_and_facility_change_in_one_save_notifies_once(self):
        gym = Facility.objects.create(name="NPalladium", source=Facility.Source.NYU)
        self.match.facility = gym
        self.match.starts_at = datetime.datetime(2026, 11, 14, 18, 0, tzinfo=NY)
        self.match.ends_at = datetime.datetime(2026, 11, 14, 20, 0, tzinfo=NY)
        self.match.save()
        self.assert_one_each("Match rescheduled")

    def test_same_time_in_another_timezone_notifies_nobody(self):
        self.match.starts_at = self.match.starts_at.astimezone(datetime.timezone.utc)
        self.match.save()
        self.assertEqual(Notification.objects.count(), 0)

    def test_unrelated_field_change_notifies_nobody(self):
        self.match.scorekeeper = self.outsider
        self.match.created_by = self.outsider
        self.match.save()
        self.match.save(update_fields=["scorekeeper"])
        self.assertEqual(Notification.objects.count(), 0)

    def test_unsaved_time_change_notifies_nobody(self):
        """update_fields leaves the new time out of the database."""
        self.match.starts_at = datetime.datetime(2026, 11, 10, 17, 0, tzinfo=NY)
        self.match.save(update_fields=["scorekeeper"])
        self.assertEqual(Notification.objects.count(), 0)

    def test_second_save_does_not_renotify(self):
        self.match.starts_at = datetime.datetime(2026, 11, 10, 17, 0, tzinfo=NY)
        self.match.save()
        self.match.save()
        self.assertEqual(Notification.objects.count(), len(self.members))

    def test_reschedule_with_first_score_sends_both(self):
        self.match.starts_at = datetime.datetime(2026, 11, 10, 17, 0, tzinfo=NY)
        self.match.home_score = 2
        self.match.away_score = 1
        self.match.save()
        verbs = sorted(self.verbs_for(self.alice))
        self.assertEqual(len(verbs), 2)
        self.assertIn("Final score", verbs[0])
        self.assertIn("Match rescheduled", verbs[1])

    def test_changing_a_cancelled_match_notifies_nobody(self):
        self.match.cancel()
        Notification.objects.all().delete()
        self.match.starts_at = datetime.datetime(2026, 11, 10, 17, 0, tzinfo=NY)
        self.match.save()
        self.assertEqual(Notification.objects.count(), 0)

    def test_long_names_fit_the_verb_column(self):
        self.match.facility = Facility.objects.create(
            name="N" + "x" * 199, source=Facility.Source.NYU
        )
        self.match.save()
        verb = self.verbs_for(self.alice)[0]
        self.assertEqual(len(verb), 255)


class MatchCancelledTests(MatchChangeFixtures):
    def test_cancel_notifies_both_rosters_once(self):
        self.match.cancel()
        self.assert_one_each("Match cancelled: NViolets vs NBobcats")

    def test_cancel_through_full_save_notifies_once(self):
        self.match.status = Match.Status.CANCELLED
        self.match.save()
        self.assert_one_each("Match cancelled")

    def test_cancel_and_reschedule_in_one_save_sends_only_cancellation(self):
        self.match.status = Match.Status.CANCELLED
        self.match.starts_at = datetime.datetime(2026, 11, 14, 18, 0, tzinfo=NY)
        self.match.ends_at = datetime.datetime(2026, 11, 14, 20, 0, tzinfo=NY)
        self.match.save()
        self.assert_one_each("Match cancelled")

    def test_resaving_a_cancelled_match_does_not_renotify(self):
        self.match.cancel()
        self.match.cancel()
        self.match.save()
        self.assertEqual(Notification.objects.count(), len(self.members))


class ScoreCorrectionTests(NotificationFixtures):
    def test_first_score_then_correction_sends_one_score_notification(self):
        match = self.make_match()
        Notification.objects.all().delete()
        match.home_score = 2
        match.away_score = 1
        match.save()
        match.home_score = 3
        match.save()
        match.save(update_fields=["home_score", "away_score"])
        verbs = self.verbs_for(self.alice)
        self.assertEqual(len(verbs), 1)
        self.assertIn("Final score", verbs[0])

    def test_first_score_through_update_fields_notifies(self):
        match = self.make_match()
        Notification.objects.all().delete()
        match.home_score = 2
        match.away_score = 1
        match.save(update_fields=["home_score", "away_score"])
        self.assertEqual(len(self.verbs_for(self.bob)), 1)

    def test_correction_on_a_fresh_instance_does_not_renotify(self):
        match = self.make_match(home_score=1, away_score=1)
        Notification.objects.all().delete()
        fresh = Match.objects.get(pk=match.pk)
        fresh.home_score = 4
        fresh.save()
        self.assertEqual(Notification.objects.count(), 0)


class OpenNotificationTests(NotificationFixtures):
    def open_url(self, note):
        return reverse("notifications:open", args=[note.pk])

    def test_view_marks_read_and_goes_to_the_link(self):
        link = reverse("matches:season_schedule", args=[self.season.pk])
        note = Notification.objects.create(recipient=self.alice, verb="One", link=link)
        self.client.force_login(self.alice)
        response = self.client.get(self.open_url(note))
        self.assertRedirects(response, link, fetch_redirect_response=False)
        note.refresh_from_db()
        self.assertTrue(note.is_read)

    def test_list_view_link_goes_through_open(self):
        note = Notification.objects.create(
            recipient=self.alice, verb="One", link="/teams/"
        )
        self.client.force_login(self.alice)
        response = self.client.get(reverse("notifications:list"))
        self.assertContains(response, f'href="{self.open_url(note)}"')
        self.assertNotContains(response, 'href="/teams/">View')

    def test_other_user_gets_404_and_row_stays_unread(self):
        note = Notification.objects.create(
            recipient=self.bob, verb="Bob note", link="/teams/"
        )
        self.client.force_login(self.alice)
        response = self.client.get(self.open_url(note))
        self.assertEqual(response.status_code, 404)
        note.refresh_from_db()
        self.assertFalse(note.is_read)

    def test_login_required(self):
        note = Notification.objects.create(
            recipient=self.alice, verb="One", link="/teams/"
        )
        response = self.client.get(self.open_url(note))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)
        note.refresh_from_db()
        self.assertFalse(note.is_read)

    def test_request_cannot_choose_the_target(self):
        note = Notification.objects.create(
            recipient=self.alice, verb="One", link="/teams/"
        )
        self.client.force_login(self.alice)
        response = self.client.get(
            self.open_url(note), {"next": "https://evil.example/"}
        )
        self.assertRedirects(response, "/teams/", fetch_redirect_response=False)

    def test_off_site_or_empty_link_goes_to_the_list(self):
        self.client.force_login(self.alice)
        for link in ("", "https://evil.example/", "//evil.example/"):
            with self.subTest(link=link):
                note = Notification.objects.create(
                    recipient=self.alice, verb="One", link=link
                )
                response = self.client.get(self.open_url(note))
                self.assertRedirects(response, reverse("notifications:list"))
                note.refresh_from_db()
                self.assertTrue(note.is_read)


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
