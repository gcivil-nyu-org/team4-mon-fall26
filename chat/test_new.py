from django.test import TestCase
from django.urls import reverse

from accounts.models import PendingAccount

from .factories import make_team, make_user
from .models import Block, Conversation


class StartChatTests(TestCase):
    def setUp(self):
        self.user = make_user("alex", first_name="Alex")
        self.team = make_team(self.user)
        self.url = reverse("chat:new")

    def make_sams(self):
        people = {}
        people["off"] = make_user("offsam", first_name="Sam", last_name="Off")
        people["off"].is_active = False
        people["off"].save()
        people["ghost"] = make_user("ghostsam", first_name="Sam", last_name="Ghost")
        PendingAccount.objects.create(user=people["ghost"], invited_by=self.user)
        people["foe"] = make_user("foesam", first_name="Sam", last_name="Foe")
        Block.objects.create(blocker=people["foe"], blocked=self.user)
        people["ok"] = make_user("oksam", first_name="Sam", last_name="Ok")
        return people

    def test_search_needs_two_characters(self):
        make_user("sally", first_name="Sally")
        self.client.force_login(self.user)
        response = self.client.get(self.url, {"q": "s"})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Sally")

    def test_search_by_first_name_shows_display_name_not_email(self):
        make_user("priya", first_name="Priya", last_name="Shah")
        self.client.force_login(self.user)
        response = self.client.get(self.url, {"q": "pr"})
        self.assertContains(response, "Priya Shah")
        self.assertNotContains(response, "priya@nyu.edu")

    def test_search_excludes_self_inactive_placeholder_and_blocked(self):
        # Self-exclusion by name is covered by the ?to=self neutral message
        # below; the navbar shows the viewer's own name, so display-name
        # assertions here cover the other three unreachable kinds.
        people = self.make_sams()
        self.client.force_login(self.user)
        response = self.client.get(self.url, {"q": "sam"})
        self.assertContains(response, "Sam Ok")
        self.assertEqual(response.content.decode().count(">Add</a>"), 1)
        for key in ("off", "ghost", "foe"):
            self.assertNotContains(response, f"Sam {people[key].last_name}")

    def test_search_does_not_match_email_prefix(self):
        make_user("zelda.k", first_name="Zed", last_name="Kim")
        self.client.force_login(self.user)
        for q in ("zel", "zelda", "zelda.k@"):
            with self.subTest(q=q):
                response = self.client.get(self.url, {"q": q})
                self.assertNotContains(response, "Zed Kim")

    def test_search_matches_full_email_exactly(self):
        make_user("zelda.k", first_name="Zed", last_name="Kim")
        self.client.force_login(self.user)
        response = self.client.get(self.url, {"q": "Zelda.K@nyu.edu"})
        self.assertContains(response, "Zed Kim")
        self.assertNotContains(response, "zelda.k@nyu.edu")

    def test_search_caps_at_20(self):
        for index in range(21):
            make_user(f"quinn{index}", first_name="Quinn", last_name=f"Q{index}")
        self.client.force_login(self.user)
        response = self.client.get(self.url, {"q": "qu"})
        self.assertEqual(response.content.decode().count(">Add</a>"), 20)

    def test_chosen_people_carry_as_hidden_inputs(self):
        friend = make_user("bea", first_name="Bea")
        self.client.force_login(self.user)
        response = self.client.get(self.url, {"q": "be", "to": [friend.pk]})
        self.assertContains(response, f'name="to" value="{friend.pk}" type="hidden"')

    def test_post_one_person_makes_direct(self):
        friend = make_user("bea")
        self.client.force_login(self.user)
        response = self.client.post(self.url, {"to": [friend.pk]})
        conversation = Conversation.objects.get(kind="direct")
        self.assertRedirects(
            response,
            reverse("chat:conversation", args=[conversation.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(conversation.memberships.count(), 2)

    def test_post_one_person_reuses_direct_started_by_other(self):
        friend = make_user("bea")
        from .factories import make_direct

        existing = make_direct(friend, self.user)
        self.client.force_login(self.user)
        response = self.client.post(self.url, {"to": [friend.pk]})
        self.assertRedirects(
            response,
            reverse("chat:conversation", args=[existing.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(Conversation.objects.filter(kind="direct").count(), 1)

    def test_duplicate_and_self_to_values_make_direct(self):
        friend = make_user("bea")
        self.client.force_login(self.user)
        self.client.post(self.url, {"to": [friend.pk, friend.pk, self.user.pk]})
        self.assertEqual(Conversation.objects.get(kind="direct").memberships.count(), 2)

    def test_post_two_people_makes_group_with_title(self):
        bea = make_user("bea")
        cal = make_user("cal")
        self.client.force_login(self.user)
        response = self.client.post(
            self.url, {"to": [bea.pk, cal.pk], "title": "Pickup crew"}
        )
        conversation = Conversation.objects.get(kind="group")
        self.assertEqual(conversation.title, "Pickup crew")
        self.assertEqual(conversation.memberships.count(), 3)
        self.assertRedirects(
            response,
            reverse("chat:conversation", args=[conversation.pk]),
            fetch_redirect_response=False,
        )

    def test_post_sixteen_people_rejected(self):
        pks = [
            make_user(f"player{index}", first_name=f"Player{index}").pk
            for index in range(16)
        ]
        self.client.force_login(self.user)
        response = self.client.post(self.url, {"to": pks})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Conversation.objects.filter(kind="group").exists())

    def test_get_to_existing_direct_redirects(self):
        friend = make_user("bea")
        from .factories import make_direct

        existing = make_direct(self.user, friend)
        self.client.force_login(self.user)
        response = self.client.get(self.url, {"to": friend.pk})
        self.assertRedirects(
            response,
            reverse("chat:conversation", args=[existing.pk]),
            fetch_redirect_response=False,
        )

    def test_get_to_new_person_writes_nothing(self):
        friend = make_user("bea", first_name="Bea")
        self.client.force_login(self.user)
        response = self.client.get(self.url, {"to": friend.pk})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bea")
        self.assertFalse(Conversation.objects.filter(kind="direct").exists())

    def test_get_to_bad_values_show_neutral_message(self):
        people = self.make_sams()
        self.client.force_login(self.user)
        for value in [
            "abc",
            self.user.pk,
            99999,
            people["off"].pk,
            people["ghost"].pk,
            people["foe"].pk,
        ]:
            response = self.client.get(self.url, {"to": value})
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "You can't message this person.")

    def test_rate_limit_refuses_21st_new_chat(self):
        friends = [make_user(f"player{index}") for index in range(21)]
        self.client.force_login(self.user)
        for friend in friends[:20]:
            response = self.client.post(self.url, {"to": [friend.pk]})
            self.assertEqual(response.status_code, 302)
        response = self.client.post(self.url, {"to": [friends[20].pk]})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "started a lot of chats")
        self.assertContains(response, "60 minutes")
        self.assertFalse(
            Conversation.objects.filter(
                direct_key=Conversation.direct_key_for(self.user, friends[20])
            ).exists()
        )

    def test_reusing_direct_does_not_count_toward_limit(self):
        friends = [make_user(f"player{index}") for index in range(21)]
        self.client.force_login(self.user)
        for friend in friends[:20]:
            self.client.post(self.url, {"to": [friend.pk]})
        response = self.client.post(self.url, {"to": [friends[0].pk]})
        self.assertEqual(response.status_code, 302)
        response = self.client.post(self.url, {"to": [friends[20].pk]})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "started a lot of chats")
