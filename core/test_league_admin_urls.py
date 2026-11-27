"""Every URL of the apps is listed as League Admin only or open (#153).

A new URL fails test_every_url_is_listed until it is added to one list. An
admin URL must turn away everyone except League Admins.
"""

import inspect

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import URLPattern, get_resolver, reverse

from accounts.roles import LEAGUE_ADMIN_ROLE, assign_role

LEAGUE_ADMIN_URLS = {
    "accounts:change_role",
    "accounts:roles",
    "chat:moderate",
    "chat:moderation_queue",
    "core:overview",
    "facilities:create",
    "facilities:edit",
    "facilities:manage",
    "forums:delete_reply",
    "forums:delete_topic",
    "forums:moderate_reply",
    "forums:moderate_topic",
    "matches:cancel",
    "matches:create",
    "matches:delete_comment",
    "matches:edit",
    "matches:manage",
    "matches:moderate_comment",
    "matches:round_robin",
    "matches:score",
    "teams:change_season_state",
    "teams:create_season",
    "teams:edit_season",
    "teams:edit_sport",
    "teams:league_setup",
    "teams:manage_divisions",
    "teams:manage_event_types",
    "teams:manage_free_agents",
    "teams:manage_season_divisions",
    "teams:manage_season_free_agents",
    "teams:manage_seasons",
    "teams:manage_sports",
    "teams:match_free_agents",
    "teams:set_scoring_event_type",
}

# Anyone, any signed-in user, or a check of its own (captain, author, scorekeeper).
OPEN_URLS = {
    "accounts:check_email",
    "accounts:resend",
    "accounts:signup",
    "accounts:verify",
    "chat:block",
    "chat:conversation",
    "chat:flag",
    "chat:inbox",
    "chat:leave",
    "chat:new",
    "chat:thread",
    "core:health",
    "core:home",
    "facilities:detail",
    "facilities:map",
    "forums:create",
    "forums:detail",
    "forums:list",
    "forums:report_reply",
    "forums:report_topic",
    "matches:detail",
    "matches:mine",
    "matches:player_leaders",
    "matches:report_comment",
    "matches:schedule",
    "matches:season_schedule",
    "matches:season_standings",
    "matches:standings",
    "matches:submit_score",
    "notifications:list",
    "notifications:mark_all_read",
    "notifications:mark_read",
    "notifications:open",
    "profiles:create",
    "profiles:detail",
    "profiles:edit",
    "teams:add_player",
    "teams:cancel_free_agent_request",
    "teams:create",
    "teams:detail",
    "teams:directory",
    "teams:disband",
    "teams:free_agent_pool",
    "teams:leave",
    "teams:list",
    "teams:remove_player",
}

GATES = ("_require_league_admin(", "can_manage_roles(")


def named_views():
    """{"namespace:name": view} for every URL of the PlayNYU apps."""
    views = {}
    for resolver in get_resolver().url_patterns:
        namespace = getattr(resolver, "namespace", None)
        if namespace in (None, "admin"):
            continue
        for pattern in resolver.url_patterns:
            assert isinstance(pattern, URLPattern), "Nested URLs: extend this test."
            assert pattern.name, f"Name the URL {pattern.pattern} in {namespace}."
            views[f"{namespace}:{pattern.name}"] = pattern
    return views


def url_for(name, pattern):
    # No such row exists. The permission check comes before the lookup, so only
    # an allowed user gets the 404.
    converters = pattern.pattern.converters
    return reverse(name, kwargs={key: 999999 for key in converters})


class LeagueAdminUrlTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.player = users.create_user("player@nyu.edu", "player@nyu.edu", "pass12345!")
        cls.admin = users.create_user("admin@nyu.edu", "admin@nyu.edu", "pass12345!")
        assign_role(cls.admin, LEAGUE_ADMIN_ROLE)

    def admin_urls(self):
        views = named_views()
        return [url_for(name, views[name]) for name in sorted(LEAGUE_ADMIN_URLS)]

    def test_every_url_is_listed(self):
        self.assertEqual(LEAGUE_ADMIN_URLS & OPEN_URLS, set())
        self.assertEqual(set(named_views()), LEAGUE_ADMIN_URLS | OPEN_URLS)

    def test_every_gated_view_is_in_the_admin_list(self):
        views = named_views()
        for name in OPEN_URLS:
            source = inspect.getsource(inspect.unwrap(views[name].callback))
            with self.subTest(url=name):
                self.assertFalse(any(gate in source for gate in GATES))

    def test_signed_out_users_are_sent_to_login(self):
        for url in self.admin_urls():
            for method in (self.client.get, self.client.post):
                with self.subTest(url=url, method=method.__name__):
                    response = method(url)
                    self.assertEqual(response.status_code, 302)
                    self.assertTrue(response.url.startswith(reverse("login")))

    def test_players_get_403(self):
        self.client.force_login(self.player)
        for url in self.admin_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url).status_code, 403)
                # A POST-only view answers a GET with 405 before its own check.
                self.assertIn(self.client.get(url).status_code, (403, 405))

    def test_league_admins_get_through(self):
        self.client.force_login(self.admin)
        for url in self.admin_urls():
            for method in (self.client.get, self.client.post):
                with self.subTest(url=url, method=method.__name__):
                    self.assertNotIn(method(url).status_code, (403, 500))
