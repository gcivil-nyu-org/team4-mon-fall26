"""#254: one scoring event type per sport, and the default event types."""

import importlib

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from .event_types import (
    create_default_event_types,
    pick_scoring_type,
    scoring_event_type,
)
from .models import EventType, Sport
from .test_league_setup import make_admin, make_user, message_texts

mark_scoring = importlib.import_module("teams.migrations.0016_mark_scoring_event_types")


class ScoringConstraintTests(TestCase):
    def setUp(self):
        self.sport = Sport.objects.create(name="Basketball")
        self.points = EventType.objects.create(
            sport=self.sport, name="Points", is_scoring=True
        )

    def test_default_is_not_scoring(self):
        assists = EventType.objects.create(sport=self.sport, name="Assists")
        self.assertFalse(assists.is_scoring)

    def test_clean_refuses_a_second_scoring_type(self):
        rebounds = EventType(sport=self.sport, name="Rebounds", is_scoring=True)
        with self.assertRaises(ValidationError) as caught:
            rebounds.full_clean()
        self.assertIn("is_scoring", caught.exception.message_dict)

    def test_clean_allows_the_same_type_again(self):
        self.points.full_clean()

    def test_another_sport_can_have_its_own_scoring_type(self):
        futsal = Sport.objects.create(name="Futsal")
        EventType.objects.create(sport=futsal, name="Goals", is_scoring=True)
        self.assertEqual(EventType.objects.filter(is_scoring=True).count(), 2)

    def test_database_refuses_a_second_scoring_type(self):
        # bulk_create skips save() and clean(), so only the constraint stops it.
        with self.assertRaises(IntegrityError), transaction.atomic():
            EventType.objects.bulk_create(
                [EventType(sport=self.sport, name="Rebounds", is_scoring=True)]
            )

    def test_many_non_scoring_types_are_allowed(self):
        EventType.objects.bulk_create(
            [
                EventType(sport=self.sport, name="Assists"),
                EventType(sport=self.sport, name="Rebounds"),
            ]
        )
        self.assertEqual(EventType.objects.count(), 3)


class ScoringEventTypeHelperTests(TestCase):
    def setUp(self):
        self.sport = Sport.objects.create(name="Basketball")

    def test_marked_type_wins_over_names(self):
        EventType.objects.create(sport=self.sport, name="Points")
        rebounds = EventType.objects.create(
            sport=self.sport, name="Rebounds", is_scoring=True
        )
        self.assertEqual(scoring_event_type(self.sport), rebounds)
        self.assertEqual(scoring_event_type(self.sport.pk), rebounds)

    def test_name_fallback_when_nothing_is_marked(self):
        EventType.objects.create(sport=self.sport, name="Assists")
        points = EventType.objects.create(sport=self.sport, name="PTS")
        self.assertEqual(scoring_event_type(self.sport), points)

    def test_none_without_a_mark_or_a_known_name(self):
        EventType.objects.create(sport=self.sport, name="Kills")
        self.assertIsNone(scoring_event_type(self.sport))
        self.assertIsNone(pick_scoring_type([]))


class MarkScoringMigrationTests(TestCase):
    """0016 marks one Points or Goals type per sport, and the reverse clears it."""

    def scoring(self, sport):
        return list(
            EventType.objects.filter(sport__name=sport, is_scoring=True).values_list(
                "name", flat=True
            )
        )

    def test_forward_marks_one_known_name_per_sport(self):
        for sport, names in {
            "Basketball": ["Assists", "points"],
            "Futsal": ["GOALS", "Goal"],
            "Rugby": ["Pts", "Point"],
            "Volleyball": ["Kills", "Aces"],
        }.items():
            created = Sport.objects.create(name=sport)
            for name in names:
                EventType.objects.create(sport=created, name=name)

        mark_scoring.mark_scoring_types(apps, None)

        self.assertEqual(self.scoring("Basketball"), ["points"])
        self.assertEqual(self.scoring("Futsal"), ["Goal"])
        self.assertEqual(self.scoring("Rugby"), ["Point"])
        self.assertEqual(self.scoring("Volleyball"), [])

    def test_forward_keeps_a_type_already_marked(self):
        sport = Sport.objects.create(name="Basketball")
        EventType.objects.create(sport=sport, name="Points")
        EventType.objects.create(sport=sport, name="Rebounds", is_scoring=True)

        mark_scoring.mark_scoring_types(apps, None)

        self.assertEqual(self.scoring("Basketball"), ["Rebounds"])

    def test_reverse_clears_every_mark(self):
        sport = Sport.objects.create(name="Basketball")
        EventType.objects.create(sport=sport, name="Points")
        mark_scoring.mark_scoring_types(apps, None)
        self.assertEqual(self.scoring("Basketball"), ["Points"])

        mark_scoring.clear_scoring_types(apps, None)

        self.assertFalse(EventType.objects.filter(is_scoring=True).exists())


class DefaultEventTypesTests(TestCase):
    def names(self, sport):
        return list(sport.event_types.order_by("pk").values_list("name", "is_scoring"))

    def test_creates_defaults_only_for_known_empty_sports(self):
        basketball = Sport.objects.create(name="basketball")
        futsal = Sport.objects.create(name="FUTSAL")
        volleyball = Sport.objects.create(name="Volleyball")
        soccer = Sport.objects.create(name="Soccer")
        EventType.objects.create(sport=futsal, name="Fouls")

        created = create_default_event_types()

        self.assertEqual(
            self.names(basketball),
            [("Points", True), ("Assists", False), ("Rebounds", False)],
        )
        self.assertEqual(self.names(futsal), [("Fouls", False)])
        self.assertEqual(self.names(volleyball), [("Kills", False), ("Aces", False)])
        self.assertEqual(self.names(soccer), [])
        self.assertEqual(
            [(sport.name, len(types)) for sport, types in created],
            [("basketball", 3), ("Volleyball", 2)],
        )
        self.assertEqual(create_default_event_types(), [])


class MarkScoringViewTests(TestCase):
    def setUp(self):
        self.sport = Sport.objects.create(name="Basketball")
        self.points = EventType.objects.create(sport=self.sport, name="Points")
        self.rebounds = EventType.objects.create(
            sport=self.sport, name="Rebounds", is_scoring=True
        )
        self.page = reverse("teams:manage_event_types")

    def url(self, event_type):
        return reverse("teams:set_scoring_event_type", args=[event_type.pk])

    def refresh(self):
        self.points.refresh_from_db()
        self.rebounds.refresh_from_db()

    def test_admin_marks_the_scoring_type(self):
        self.client.force_login(make_admin())

        response = self.client.post(self.url(self.points), {"scoring": "on"})

        self.assertRedirects(response, self.page)
        self.refresh()
        self.assertTrue(self.points.is_scoring)
        self.assertFalse(self.rebounds.is_scoring)
        self.assertIn(
            "Points is now the scoring stat for Basketball.",
            message_texts(response),
        )

    def test_admin_clears_the_scoring_type(self):
        self.client.force_login(make_admin())

        response = self.client.post(self.url(self.rebounds), {"scoring": "off"})

        self.assertRedirects(response, self.page)
        self.refresh()
        self.assertFalse(self.rebounds.is_scoring)
        self.assertIn("Basketball has no scoring stat.", message_texts(response))

    def test_page_shows_the_mark_and_the_actions(self):
        self.client.force_login(make_admin())

        response = self.client.get(self.page)

        self.assertContains(response, "Scoring stat</span>")
        self.assertContains(response, f'action="{self.url(self.points)}"')
        self.assertContains(response, f'action="{self.url(self.rebounds)}"')

    def test_non_admin_is_refused(self):
        self.client.force_login(make_user("player"))

        response = self.client.post(self.url(self.points), {"scoring": "on"})

        self.assertEqual(response.status_code, 403)
        self.refresh()
        self.assertFalse(self.points.is_scoring)
        self.assertTrue(self.rebounds.is_scoring)

    def test_anonymous_is_sent_to_login(self):
        response = self.client.post(self.url(self.points), {"scoring": "on"})
        self.assertEqual(response.status_code, 302)
        self.refresh()
        self.assertFalse(self.points.is_scoring)

    def test_get_is_not_allowed(self):
        self.client.force_login(make_admin())
        self.assertEqual(self.client.get(self.url(self.points)).status_code, 405)

    def test_unknown_event_type_is_404(self):
        self.client.force_login(make_admin())
        response = self.client.post(
            reverse("teams:set_scoring_event_type", args=[999999]), {"scoring": "on"}
        )
        self.assertEqual(response.status_code, 404)
