"""The roles page (#261): list, filters, POST changes, entry points."""

from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.roles import (
    CASUAL_PLAYER_ROLE,
    LEAGUE_ADMIN_ROLE,
    SCOREKEEPER_ROLE,
    assign_role,
    has_role,
)
from accounts.test_role_admin import RoleFixtures, make_user, role_rows

ROLES_URL = reverse("accounts:roles")


class RoleListAccessTests(RoleFixtures):
    def test_anonymous_goes_to_login(self):
        response = self.client.get(ROLES_URL)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_casual_player_and_scorekeeper_get_403(self):
        for email, role in (
            ("casual@nyu.edu", CASUAL_PLAYER_ROLE),
            ("sk@nyu.edu", SCOREKEEPER_ROLE),
        ):
            with self.subTest(role):
                self.client.force_login(make_user(email, role=role))
                self.assertEqual(self.client.get(ROLES_URL).status_code, 403)

    def test_league_admin_and_superuser_get_200(self):
        for user in (self.boss, self.root):
            with self.subTest(user.email):
                self.client.force_login(user)
                self.assertEqual(self.client.get(ROLES_URL).status_code, 200)

    def test_league_setup_is_highlighted(self):
        self.client.force_login(self.boss)
        response = self.client.get(ROLES_URL)
        self.assertEqual(response.context["nav_section"], "league_setup")


class RoleListContentTests(RoleFixtures):
    def setUp(self):
        self.client.force_login(self.boss)

    def listed(self, **params):
        response = self.client.get(ROLES_URL, params)
        self.assertEqual(response.status_code, 200)
        return [row.email for row in response.context["page_obj"]]

    def test_placeholder_and_inactive_users_are_not_listed(self):
        make_user("gone@nyu.edu", "Gone", "User", is_active=False)
        emails = self.listed()
        self.assertNotIn("ghost@nyu.edu", emails)
        self.assertNotIn("gone@nyu.edu", emails)
        self.assertIn("alex@nyu.edu", emails)
        self.assertIn("root@nyu.edu", emails)

    def test_search_matches_first_last_full_name_and_email(self):
        make_user("sam@nyu.edu", "Sam", "Kim")
        for query in ("alex", "LEE", "alex lee", "alex@nyu"):
            with self.subTest(query):
                emails = self.listed(q=query)
                self.assertIn("alex@nyu.edu", emails)
                self.assertNotIn("sam@nyu.edu", emails)
        self.assertEqual(self.listed(q="alex lee"), ["alex@nyu.edu"])

    def test_role_filter_shows_holders_only(self):
        assign_role(self.alex, SCOREKEEPER_ROLE)
        self.assertEqual(self.listed(role="scorekeeper"), ["alex@nyu.edu"])
        self.assertEqual(self.listed(role="league_admin"), ["boss@nyu.edu"])

    def test_bad_role_value_is_ignored(self):
        self.assertEqual(len(self.listed(role="bogus")), 4)

    def test_long_query_is_ignored(self):
        self.assertEqual(len(self.listed(q="x" * 200)), 4)

    def test_pages_keep_the_filters(self):
        for n in range(21):
            make_user(f"player{n:02}@nyu.edu", "Player", f"{n:02}")
        response = self.client.get(ROLES_URL, {"q": "player", "role": "", "page": 1})
        self.assertEqual(response.context["page_obj"].paginator.num_pages, 2)
        self.assertContains(response, "?q=player&amp;page=2")
        self.assertContains(response, '<span class="pn-num">21</span> people')

    def test_out_of_range_page_gives_the_last_page(self):
        response = self.client.get(ROLES_URL, {"page": 999})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].number, 1)

    def test_email_is_labelled(self):
        self.assertContains(
            self.client.get(ROLES_URL),
            '<span class="visually-hidden">Email: </span>alex@nyu.edu',
            html=False,
        )

    def test_own_and_last_league_admin_remove_is_disabled(self):
        response = self.client.get(ROLES_URL)
        self.assertContains(
            response,
            'disabled title="You can\'t remove your own League Admin role"',
            count=1,
        )
        self.assertContains(response, " disabled", count=1)

    def test_last_league_admin_reason_for_another_viewer(self):
        self.client.force_login(self.root)
        response = self.client.get(ROLES_URL)
        self.assertContains(
            response,
            'disabled title="The league needs at least one League Admin"',
            count=1,
        )
        self.assertNotContains(response, 'title="You can')

    def test_two_league_admins_can_remove_each_other(self):
        assign_role(self.alex, LEAGUE_ADMIN_ROLE)
        response = self.client.get(ROLES_URL)
        self.assertNotContains(response, 'title="The league needs')
        self.assertContains(response, " disabled", count=1)  # only the viewer's row

    def test_superuser_row_has_site_admin_badge(self):
        self.assertContains(self.client.get(ROLES_URL), "Site admin", count=2)
        # The badge, and the About roles rule.

    def test_unscored_count_and_needs_reassigning_badge(self):
        assign_role(self.alex, SCOREKEEPER_ROLE)
        self.make_match(self.alex)
        self.make_match(self.alex)
        sam = make_user("sam@nyu.edu", "Sam", "Kim")
        self.make_match(sam)
        response = self.client.get(ROLES_URL)
        self.assertContains(
            response, 'Assigned to <span class="pn-num">2</span> unscored matches'
        )
        self.assertContains(
            response, 'Assigned to <span class="pn-num">1</span> unscored match<'
        )
        self.assertContains(response, "Needs reassigning", count=1)

    def test_empty_state(self):
        response = self.client.get(ROLES_URL, {"q": "zzz"})
        self.assertContains(response, "No one matches these filters.")
        self.assertContains(response, "Clear filters")

    def test_query_count_does_not_grow_with_rows(self):
        counts = []
        for total in (2, 20):
            for n in range(total):
                user = make_user(f"u{total}-{n}@nyu.edu", "User", f"{total}-{n}")
                assign_role(user, SCOREKEEPER_ROLE)
                self.make_match(user)
            with CaptureQueriesContext(connection) as ctx:
                response = self.client.get(ROLES_URL)
            self.assertEqual(response.status_code, 200)
            counts.append(len(ctx))
        self.assertEqual(counts[0], counts[1], counts)


class ChangeRoleViewTests(RoleFixtures):
    def setUp(self):
        self.client.force_login(self.boss)

    def url(self, user):
        return reverse("accounts:change_role", args=[user.pk])

    def post(self, user, **data):
        defaults = {"role": "scorekeeper", "action": "add"}
        return self.client.post(self.url(user), {**defaults, **data})

    def messages_of(self, response):
        # Follow the redirect, so the next post starts with no queued messages.
        page = self.client.get(response["Location"])
        return [(m.level_tag, m.message) for m in page.context["messages"]]

    def test_get_is_405(self):
        self.assertEqual(self.client.get(self.url(self.alex)).status_code, 405)

    def test_casual_player_gets_403_and_nothing_changes(self):
        self.client.force_login(make_user("casual@nyu.edu", role=CASUAL_PLAYER_ROLE))
        self.assertEqual(self.post(self.alex).status_code, 403)
        self.assertFalse(has_role(self.alex, SCOREKEEPER_ROLE))

    def test_csrf_is_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.boss)
        response = client.post(
            self.url(self.alex), {"role": "scorekeeper", "action": "add"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(has_role(self.alex, SCOREKEEPER_ROLE))

    def test_placeholder_and_inactive_targets_are_404(self):
        gone = make_user("gone@nyu.edu", "Gone", "User", is_active=False)
        for target in (self.ghost, gone):
            with self.subTest(target.email):
                self.assertEqual(self.post(target).status_code, 404)
                self.assertFalse(has_role(target, SCOREKEEPER_ROLE))

    def test_bad_role_or_action_is_400(self):
        for data in (
            {"role": "casual_player"},
            {"role": ""},
            {"action": "toggle"},
        ):
            with self.subTest(data):
                self.assertEqual(self.post(self.alex, **data).status_code, 400)
        self.assertFalse(role_rows().exists())

    def test_add_redirects_back_with_filters_and_page(self):
        response = self.post(self.alex, q="lee", role_filter="scorekeeper", page="3")
        self.assertRedirects(
            response,
            ROLES_URL + "?q=lee&role=scorekeeper&page=3",
            fetch_redirect_response=False,
        )

    def test_bad_return_values_are_dropped(self):
        response = self.post(self.alex, role_filter="bogus", page="abc", q="")
        self.assertRedirects(response, ROLES_URL, fetch_redirect_response=False)

    def test_success_message(self):
        response = self.post(self.alex)
        self.assertTrue(has_role(self.alex, SCOREKEEPER_ROLE))
        self.assertEqual(
            self.messages_of(response), [("success", "Alex Lee is now a Scorekeeper.")]
        )

    def test_league_admin_messages(self):
        response = self.post(self.alex, role="league_admin")
        self.assertEqual(
            self.messages_of(response), [("success", "Alex Lee is now a League Admin.")]
        )
        response = self.post(self.alex, role="league_admin", action="remove")
        self.assertEqual(
            self.messages_of(response),
            [("success", "Alex Lee is no longer a League Admin.")],
        )

    def test_double_post_logs_once(self):
        self.messages_of(self.post(self.alex))
        response = self.post(self.alex)
        self.assertEqual(
            self.messages_of(response), [("info", "Alex Lee is already a Scorekeeper.")]
        )
        self.assertEqual(role_rows().count(), 1)

    def test_removing_a_missing_role_says_so(self):
        response = self.post(self.alex, action="remove")
        self.assertEqual(
            self.messages_of(response), [("info", "Alex Lee isn't a Scorekeeper.")]
        )

    def test_refusals_show_error_messages(self):
        response = self.post(self.boss, role="league_admin", action="remove")
        self.assertEqual(
            self.messages_of(response),
            [
                (
                    "error",
                    "You can't remove your own League Admin role. "
                    "Ask another League Admin.",
                )
            ],
        )
        self.client.force_login(self.root)
        response = self.post(self.boss, role="league_admin", action="remove")
        self.assertEqual(
            self.messages_of(response),
            [
                (
                    "error",
                    "Lee Admin is the last League Admin. "
                    "Make someone else a League Admin first.",
                )
            ],
        )
        self.assertTrue(has_role(self.boss, LEAGUE_ADMIN_ROLE))

    def test_scorekeeper_removal_warns_about_unscored_matches(self):
        assign_role(self.alex, SCOREKEEPER_ROLE)
        for _ in range(3):
            self.make_match(self.alex)
        response = self.post(self.alex, action="remove")
        self.assertEqual(
            self.messages_of(response),
            [
                ("success", "Alex Lee is no longer a Scorekeeper."),
                (
                    "warning",
                    "Alex Lee still has 3 unscored matches and can't score them now. "
                    "Choose another scorekeeper on Manage matches.",
                ),
            ],
        )

    def test_one_unscored_match_is_singular(self):
        assign_role(self.alex, SCOREKEEPER_ROLE)
        self.make_match(self.alex)
        response = self.post(self.alex, action="remove")
        self.assertIn(
            "still has 1 unscored match and", self.messages_of(response)[1][1]
        )

    def test_nameless_target_message_has_no_email(self):
        response = self.post(self.nameless)
        self.assertEqual(
            self.messages_of(response),
            [("success", "PlayNYU player is now a Scorekeeper.")],
        )
