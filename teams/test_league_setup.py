"""#109: League Admin configuration workflow (hub, permissions, create flows, transitions)."""

import datetime

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from accounts.roles import LEAGUE_ADMIN_ROLE, assign_role

from .models import Division, EventType, FreeAgentRequest, Season, Sport
from .season_rules import SeasonState


def make_user(username):
    return get_user_model().objects.create_user(
        username=username, email=f"{username}@nyu.edu", password="pass12345!"
    )


def make_admin(username="admin"):
    user = make_user(username)
    assign_role(user, LEAGUE_ADMIN_ROLE)
    return user


def make_superuser(username="root"):
    return get_user_model().objects.create_superuser(
        username=username, email=f"{username}@nyu.edu", password="pass12345!"
    )


def make_season(name="Fall", state=SeasonState.OPEN):
    return Season.objects.create(
        name=name, start_date=datetime.date(2026, 9, 1), state=state
    )


def message_texts(response):
    return [str(message) for message in get_messages(response.wsgi_request)]


class LeagueSetupPermissionTests(TestCase):
    """Every configuration page: anonymous -> login, player -> 403, admins -> 200."""

    def setUp(self):
        self.season = make_season()
        self.urls = [
            reverse("teams:league_setup"),
            reverse("teams:manage_sports"),
            reverse("teams:manage_event_types"),
            reverse("teams:manage_divisions"),
            reverse("teams:manage_season_divisions", args=[self.season.pk]),
            reverse("teams:manage_seasons"),
            reverse("teams:create_season"),
            reverse("teams:edit_season", args=[self.season.pk]),
        ]

    def test_anonymous_user_is_redirected_to_login(self):
        for url in self.urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("login"), response.url)

    def test_player_is_forbidden(self):
        self.client.force_login(make_user("player"))
        for url in self.urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_league_admin_and_superuser_can_open_every_page(self):
        for user in (make_admin(), make_superuser()):
            self.client.force_login(user)
            for url in self.urls:
                with self.subTest(user=user.username, url=url):
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 200)
                    self.assertTemplateUsed(response, "base.html")


class ForbiddenSubmissionTests(TestCase):
    """Non-admins can't change configuration by posting directly."""

    def setUp(self):
        self.season = make_season()
        self.sport = Sport.objects.create(name="Soccer")
        self.posts = [
            (reverse("teams:manage_sports"), {"name": "Rugby"}),
            (
                reverse("teams:manage_event_types"),
                {"sport": self.sport.pk, "name": "Pickup"},
            ),
            (
                reverse("teams:manage_season_divisions", args=[self.season.pk]),
                {"name": "East"},
            ),
            (
                reverse("teams:create_season"),
                {"name": "Spring", "start_date": "2027-01-10", "max_roster_size": 12},
            ),
            (
                reverse("teams:edit_season", args=[self.season.pk]),
                {"name": "Renamed", "start_date": "2026-09-01", "max_roster_size": 12},
            ),
            (
                reverse("teams:change_season_state", args=[self.season.pk]),
                {"state": SeasonState.ACTIVE},
            ),
        ]

    def assert_nothing_created(self):
        self.assertEqual(list(Sport.objects.values_list("name", flat=True)), ["Soccer"])
        self.assertFalse(EventType.objects.exists())
        self.assertFalse(Division.objects.exists())
        self.assertEqual(
            list(Season.objects.values_list("name", "state")),
            [("Fall", SeasonState.OPEN)],
        )

    def test_player_post_is_forbidden_and_creates_nothing(self):
        self.client.force_login(make_user("player"))
        for url, data in self.posts:
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url, data).status_code, 403)
        self.assert_nothing_created()

    def test_anonymous_post_redirects_to_login_and_creates_nothing(self):
        for url, data in self.posts:
            with self.subTest(url=url):
                response = self.client.post(url, data)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("login"), response.url)
        self.assert_nothing_created()


class LeagueSetupHubTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.url = reverse("teams:league_setup")

    def test_hub_links_to_every_configuration_page_with_counts(self):
        season = make_season()
        soccer = Sport.objects.create(name="Soccer")
        Sport.objects.create(name="Tennis")
        EventType.objects.create(sport=soccer, name="Pickup")
        Division.objects.create(season=season, name="East")
        FreeAgentRequest.objects.create(
            player=make_user("freeagent"), season=season, sport=soccer
        )
        self.client.force_login(self.admin)

        response = self.client.get(self.url)

        self.assertContains(response, "<h1>League setup</h1>", html=True)
        for name in (
            "manage_seasons",
            "manage_sports",
            "manage_event_types",
            "manage_divisions",
            "manage_free_agents",
        ):
            self.assertContains(response, f'href="{reverse(f"teams:{name}")}"')
        self.assertEqual(
            response.context["counts"],
            {
                "seasons": 1,
                "sports": 2,
                "event_types": 1,
                "divisions": 1,
                "waiting_requests": 1,
            },
        )

    def test_waiting_requests_only_count_seasons_that_can_be_matched(self):
        soccer = Sport.objects.create(name="Soccer")
        for state in SeasonState.values:
            season = make_season(name=state.title(), state=state)
            FreeAgentRequest.objects.create(
                player=make_user(f"fa_{state}"), season=season, sport=soccer
            )
        self.client.force_login(self.admin)

        response = self.client.get(self.url)

        # Open and active seasons can be matched; draft and closed can't.
        self.assertEqual(response.context["counts"]["waiting_requests"], 2)

    def test_nav_link_is_shown_to_admins_only(self):
        link = f'href="{self.url}"'
        self.client.force_login(make_user("player"))
        self.assertNotContains(self.client.get(reverse("teams:list")), link)

        for user in (self.admin, make_superuser()):
            self.client.force_login(user)
            with self.subTest(user=user.username):
                self.assertContains(self.client.get(reverse("teams:list")), link)

    def test_configuration_pages_mark_league_setup_as_current_nav_item(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("teams:manage_sports"))
        self.assertContains(
            response,
            f'<a class="nav-link" href="{self.url}" aria-current="page">',
        )
        self.assertNotContains(
            response,
            f'<a class="nav-link" href="{reverse("teams:list")}" aria-current="page">',
        )


class ManageSportsFlowTests(TestCase):
    def setUp(self):
        self.client.force_login(make_admin())
        self.url = reverse("teams:manage_sports")

    def test_admin_adds_a_sport_with_a_normalized_name(self):
        response = self.client.post(self.url, {"name": "  Ultimate   Frisbee "})

        self.assertRedirects(response, self.url)
        self.assertIn("Sport added successfully.", message_texts(response))
        self.assertTrue(Sport.objects.filter(name="Ultimate Frisbee").exists())

    def test_duplicate_ignoring_case_and_spaces_shows_a_field_error(self):
        Sport.objects.create(name="Ultimate Frisbee")

        response = self.client.post(self.url, {"name": " ultimate  frisbee"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["form"].errors["name"],
            ["A sport with this name already exists."],
        )
        self.assertContains(response, "A sport with this name already exists.")
        self.assertNotContains(response, "{&#x27;name&#x27;")
        self.assertEqual(Sport.objects.count(), 1)

    def test_blank_and_too_long_names_are_rejected(self):
        for name in ("   ", "A" * 51):
            with self.subTest(name=name):
                response = self.client.post(self.url, {"name": name})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors["name"])
                self.assertContains(response, "invalid-feedback")
        self.assertFalse(Sport.objects.exists())

    def test_empty_state_when_no_sports_exist(self):
        response = self.client.get(self.url)
        self.assertContains(response, "No sports yet")


class ManageEventTypesFlowTests(TestCase):
    def setUp(self):
        self.client.force_login(make_admin())
        self.url = reverse("teams:manage_event_types")
        self.soccer = Sport.objects.create(name="Soccer")
        self.basketball = Sport.objects.create(name="Basketball")

    def test_admin_adds_an_event_type(self):
        response = self.client.post(
            self.url, {"sport": self.soccer.pk, "name": " Pickup "}
        )

        self.assertRedirects(response, self.url)
        self.assertIn("Event type added successfully.", message_texts(response))
        self.assertTrue(
            EventType.objects.filter(sport=self.soccer, name="Pickup").exists()
        )

    def test_same_name_is_allowed_under_another_sport(self):
        EventType.objects.create(sport=self.soccer, name="Pickup")

        response = self.client.post(
            self.url, {"sport": self.basketball.pk, "name": "pickup"}
        )

        self.assertRedirects(response, self.url)
        self.assertEqual(EventType.objects.count(), 2)

    def test_duplicate_within_a_sport_shows_a_field_error(self):
        EventType.objects.create(sport=self.soccer, name="Pickup")

        response = self.client.post(
            self.url, {"sport": self.soccer.pk, "name": " PICKUP"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["form"].errors["name"],
            ["An event type with this name already exists for this sport."],
        )
        self.assertEqual(EventType.objects.count(), 1)

    def test_missing_or_invalid_sport_is_a_form_error_not_a_crash(self):
        for sport in ("", "abc", "999999"):
            with self.subTest(sport=sport):
                response = self.client.post(self.url, {"sport": sport, "name": "3v3"})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors["sport"])
        self.assertFalse(EventType.objects.exists())

    def test_form_is_replaced_by_a_prompt_when_no_sports_exist(self):
        Sport.objects.all().delete()

        response = self.client.get(self.url)

        self.assertContains(response, "Add a sport first.")
        self.assertContains(response, f'href="{reverse("teams:manage_sports")}"')
        self.assertNotContains(response, "Add event type</button>")


class ManageDivisionsFlowTests(TestCase):
    """Create flow gaps not covered by test_divisions.DivisionManagementTests."""

    def setUp(self):
        self.client.force_login(make_admin())
        self.season = make_season()
        self.url = reverse("teams:manage_season_divisions", args=[self.season.pk])

    def test_success_message_names_the_division_and_season(self):
        response = self.client.post(self.url, {"name": "East"})

        self.assertRedirects(response, self.url)
        self.assertIn("Added East to Fall.", message_texts(response))

    def test_blank_name_shows_a_field_error(self):
        response = self.client.post(self.url, {"name": "   "})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors["name"])
        self.assertFalse(Division.objects.exists())

    def test_unknown_season_is_not_found(self):
        url = reverse("teams:manage_season_divisions", args=[self.season.pk + 1])
        self.assertEqual(self.client.get(url).status_code, 404)


class SeasonTransitionViewTests(TestCase):
    """Invalid state changes through the seasons page: error shown, state unchanged."""

    def setUp(self):
        self.client.force_login(make_admin())

    def post_state(self, season, target):
        return self.client.post(
            reverse("teams:change_season_state", args=[season.pk]),
            {"state": target},
        )

    def test_invalid_transitions_are_rejected(self):
        cases = [
            (SeasonState.CLOSED, SeasonState.OPEN, "Closed to Open"),
            (SeasonState.CLOSED, SeasonState.DRAFT, "Closed to Draft"),
            (SeasonState.CLOSED, SeasonState.ACTIVE, "Closed to Active"),
            (SeasonState.DRAFT, SeasonState.ACTIVE, "Draft to Active"),
            (SeasonState.DRAFT, SeasonState.CLOSED, "Draft to Closed"),
            (SeasonState.OPEN, SeasonState.CLOSED, "Open to Closed"),
            (SeasonState.ACTIVE, SeasonState.OPEN, "Active to Open"),
            (SeasonState.ACTIVE, SeasonState.DRAFT, "Active to Draft"),
        ]
        for current, target, label in cases:
            with self.subTest(current=current, target=target):
                season = make_season(name=f"{current}-{target}", state=current)
                response = self.post_state(season, target)
                self.assertRedirects(response, reverse("teams:manage_seasons"))
                self.assertIn(
                    f"A season can't move from {label}.", message_texts(response)
                )
                season.refresh_from_db()
                self.assertEqual(season.state, current)

    def test_moving_to_the_same_state_is_rejected(self):
        for state in SeasonState.values:
            with self.subTest(state=state):
                season = make_season(name=f"Same {state}", state=state)
                label = SeasonState(state).label
                response = self.post_state(season, state)
                self.assertIn(
                    f"A season can't move from {label} to {label}.",
                    message_texts(response),
                )
                season.refresh_from_db()
                self.assertEqual(season.state, state)

    def test_unknown_or_missing_state_is_rejected(self):
        season = make_season(state=SeasonState.DRAFT)
        for target in ("archived", ""):
            with self.subTest(target=target):
                response = self.post_state(season, target)
                self.assertTrue(
                    any(
                        text.startswith("A season can't move from Draft to")
                        for text in message_texts(response)
                    )
                )
        season.refresh_from_db()
        self.assertEqual(season.state, SeasonState.DRAFT)

    def test_open_season_can_be_pulled_back_to_draft(self):
        season = make_season(state=SeasonState.OPEN)

        response = self.post_state(season, SeasonState.DRAFT)

        self.assertIn("Fall is now draft.", message_texts(response))
        season.refresh_from_db()
        self.assertEqual(season.state, SeasonState.DRAFT)
