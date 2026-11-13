"""#211: top navbar items for each role, and where the admin pages are linked."""

import re

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.roles import LEAGUE_ADMIN_ROLE, SCOREKEEPER_ROLE, assign_role

PLAYER_ITEMS = ["Home", "My teams", "Free agents", "Schedule", "Facilities", "Forum"]


def make_user(username, *roles):
    user = get_user_model().objects.create_user(
        username=username, email=f"{username}@nyu.edu", password="pass12345!"
    )
    for role in roles:
        assign_role(user, role)
    return user


def top_nav(response):
    """The HTML of the collapsible list of top-level items."""
    html = response.content.decode()
    return re.search(r'<ul class="navbar-nav[^"]*">.*?</ul>', html, re.S).group(0)


def nav_labels(response):
    return [
        label.strip() for label in re.findall(r"</i>([^<]+)</a>", top_nav(response))
    ]


def active_labels(response):
    return [
        label.strip()
        for label in re.findall(
            r'aria-current="page"><i[^>]*></i>([^<]+)</a>', top_nav(response)
        )
    ]


class NavbarItemTests(TestCase):
    def setUp(self):
        self.seasons_url = reverse("teams:manage_seasons")
        self.placement_url = reverse("teams:manage_free_agents")

    def get_nav(self, user):
        self.client.force_login(user)
        return self.client.get(reverse("teams:list"))

    def test_player_sees_only_the_shared_items(self):
        self.assertEqual(nav_labels(self.get_nav(make_user("player"))), PLAYER_ITEMS)

    def test_scorekeeper_also_sees_my_matches(self):
        response = self.get_nav(make_user("keeper", SCOREKEEPER_ROLE))
        self.assertEqual(nav_labels(response), PLAYER_ITEMS + ["My matches"])

    def test_admin_sees_overview_and_league_setup_without_seasons_or_placement(self):
        superuser = get_user_model().objects.create_superuser(
            "root", "root@nyu.edu", "pass12345!"
        )
        for user in (make_user("admin", LEAGUE_ADMIN_ROLE), superuser):
            with self.subTest(user=user.username):
                response = self.get_nav(user)
                self.assertEqual(
                    nav_labels(response), PLAYER_ITEMS + ["Overview", "League setup"]
                )
                nav = top_nav(response)
                self.assertIn(f'href="{reverse("core:overview")}"', nav)
                self.assertIn(f'href="{reverse("teams:league_setup")}"', nav)
                self.assertNotIn(self.seasons_url, nav)
                self.assertNotIn(self.placement_url, nav)

    def test_admin_scorekeeper_sees_every_item_in_order(self):
        user = make_user("both", LEAGUE_ADMIN_ROLE, SCOREKEEPER_ROLE)
        self.assertEqual(
            nav_labels(self.get_nav(user)),
            PLAYER_ITEMS + ["My matches", "Overview", "League setup"],
        )

    def test_labels_do_not_wrap_and_icons_hide_in_the_wide_layout(self):
        response = self.get_nav(make_user("both", LEAGUE_ADMIN_ROLE, SCOREKEEPER_ROLE))
        html = response.content.decode()
        nav = top_nav(response)
        self.assertIn('<header class="navbar navbar-expand-xl d-print-none">', html)
        self.assertIn('<ul class="navbar-nav text-nowrap">', nav)
        self.assertIn("flex-nowrap text-nowrap order-xl-last", html)
        self.assertEqual(nav.count('<i aria-hidden="true"'), 9)
        self.assertEqual(nav.count("me-2 d-xl-none"), 9)
        self.assertIn('class="d-none d-xxl-block ps-2"', html)
        self.assertIn("text-truncate pn-nav-name", html)


class AdminPageLinkTests(TestCase):
    """Seasons and Placement left the navbar; these pages still link to both."""

    def setUp(self):
        self.client.force_login(make_user("admin", LEAGUE_ADMIN_ROLE))
        self.links = [
            f'href="{reverse("teams:manage_seasons")}"',
            f'href="{reverse("teams:manage_free_agents")}"',
        ]

    def test_league_setup_links_to_seasons_and_placement(self):
        response = self.client.get(reverse("teams:league_setup"))
        for link in self.links:
            self.assertContains(response, link)

    def test_overview_links_to_seasons_and_placement(self):
        response = self.client.get(reverse("core:overview"))
        for link in self.links:
            self.assertContains(response, link)


class AdminPageHighlightTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user("admin", LEAGUE_ADMIN_ROLE))

    def test_seasons_and_placement_pages_highlight_league_setup(self):
        for name in ("teams:manage_seasons", "teams:manage_free_agents"):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(active_labels(response), ["League setup"])

    def test_team_list_still_highlights_my_teams(self):
        response = self.client.get(reverse("teams:list"))
        self.assertEqual(active_labels(response), ["My teams"])
