from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import PlayerProfile


# TODO(T10): switch to the shared fixtures once they land.
def make_user(username, first_name="Alex", last_name="Lee", n_number=None, net_id=None):
    user = get_user_model().objects.create_user(
        username=username,
        email=f"{username}@nyu.edu",
        password="pass12345!",
        first_name=first_name,
        last_name=last_name,
    )
    if n_number or net_id:
        PlayerProfile.objects.create(user=user, n_number=n_number, net_id=net_id)
    return user


VALID = {"first_name": "Sam", "last_name": "Park", "n_number": "N87654321", "net_id": "sp9876"}


class EditProfileTests(TestCase):
    def setUp(self):
        self.user = make_user("owner", n_number="N12345678", net_id="al1234")
        self.url = reverse("profiles:edit", args=[self.user.pk])
        self.client.force_login(self.user)

    def assert_unchanged(self):
        self.user.refresh_from_db()
        profile = self.user.player_profile
        profile.refresh_from_db()
        self.assertEqual(
            (self.user.first_name, self.user.last_name, profile.n_number, profile.net_id),
            ("Alex", "Lee", "N12345678", "al1234"),
        )

    def test_form_shows_current_values(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        for value in ("Alex", "Lee", "N12345678", "al1234"):
            self.assertContains(response, f'value="{value}"')

    def test_email_is_not_on_the_form(self):
        response = self.client.get(self.url)
        self.assertNotContains(response, 'name="email"')

    def test_valid_update_is_saved(self):
        response = self.client.post(self.url, VALID, follow=True)
        self.user.refresh_from_db()
        profile = PlayerProfile.objects.get(user=self.user)
        self.assertEqual(
            (self.user.first_name, self.user.last_name, profile.n_number, profile.net_id),
            ("Sam", "Park", "N87654321", "sp9876"),
        )
        self.assertContains(response, "Your profile has been updated.")

    def test_values_are_normalised(self):
        self.client.post(self.url, {**VALID, "n_number": " n87654321 ", "net_id": "SP9876"})
        profile = PlayerProfile.objects.get(user=self.user)
        self.assertEqual((profile.n_number, profile.net_id), ("N87654321", "sp9876"))

    def test_edit_without_profile_redirects_to_create(self):
        newcomer = make_user("newcomer")
        self.client.force_login(newcomer)
        response = self.client.post(reverse("profiles:edit", args=[newcomer.pk]), VALID)
        self.assertRedirects(response, reverse("profiles:create"))
        self.assertFalse(PlayerProfile.objects.filter(user=newcomer).exists())

    def test_valid_update_redirects_so_refresh_does_not_resubmit(self):
        response = self.client.post(self.url, VALID)
        self.assertEqual(response.status_code, 302)

    def test_email_cannot_be_changed(self):
        self.client.post(self.url, {**VALID, "email": "new@nyu.edu"})
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "owner@nyu.edu")

    def test_blank_field_rejected_and_nothing_saved(self):
        response = self.client.post(self.url, {**VALID, "first_name": "   "})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required.")
        self.assertContains(response, "Your profile was not updated.")
        self.assertNotContains(response, "Your profile has been updated.")
        self.assert_unchanged()

    def test_invalid_n_number_rejected(self):
        for bad in ("12345678", "N1234567", "N123456789", "X12345678"):
            response = self.client.post(self.url, {**VALID, "n_number": bad})
            self.assertContains(response, "N followed by 8 digits")
        self.assert_unchanged()

    def test_invalid_net_id_rejected(self):
        for bad in ("1234", "abc", "ab-12", "ab 12"):
            response = self.client.post(self.url, {**VALID, "net_id": bad})
            self.assertContains(response, "letters followed by digits")
        self.assert_unchanged()

    def test_duplicate_n_number_and_net_id_rejected(self):
        make_user("other", n_number="N87654321", net_id="sp9876")
        response = self.client.post(self.url, VALID)
        self.assertContains(response, "This N number is already used by another account.")
        self.assertContains(response, "This NetID is already used by another account.")
        self.assert_unchanged()

    def test_rejected_update_keeps_entered_values(self):
        response = self.client.post(self.url, {**VALID, "first_name": ""})
        self.assertContains(response, 'value="Park"')
        self.assertContains(response, 'value="N87654321"')

    def test_retry_after_rejection_is_saved(self):
        self.client.post(self.url, {**VALID, "n_number": "bad"})
        response = self.client.post(self.url, VALID)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(PlayerProfile.objects.get(user=self.user).n_number, "N87654321")

    def test_other_users_profile_is_forbidden(self):
        other = make_user("other", first_name="Jo", last_name="Kim")
        url = reverse("profiles:edit", args=[other.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        response = self.client.post(url, {**VALID, "first_name": "Hacked"})
        self.assertEqual(response.status_code, 403)
        other.refresh_from_db()
        self.assertEqual(other.first_name, "Jo")
        self.assertFalse(PlayerProfile.objects.filter(user=other).exists())

    def test_missing_user_is_404(self):
        response = self.client.get(reverse("profiles:edit", args=[99999]))
        self.assertEqual(response.status_code, 404)

    def test_signed_out_user_is_sent_to_login(self):
        self.client.logout()
        response = self.client.post(self.url, VALID)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)
        self.assert_unchanged()

    def test_nav_links_to_my_profile(self):
        response = self.client.get(reverse("teams:list"))
        self.assertContains(response, reverse("profiles:detail", args=[self.user.pk]))


class ProfileDetailTests(TestCase):
    def setUp(self):
        from teams.models import Roster, Team

        self.owner = make_user("owner", n_number="N12345678", net_id="al1234")
        self.viewer = make_user("viewer", first_name="Jo", last_name="Kim")
        self.url = reverse("profiles:detail", args=[self.owner.pk])
        mine = Team.objects.create(name="Violets", sport="Soccer", captain=self.owner)
        Roster.objects.create(team=mine, player=self.owner, role=Roster.Role.CAPTAIN)
        self.shared = mine
        other = Team.objects.create(name="Bobcats", sport="Basketball", captain=self.owner)
        Roster.objects.create(team=other, player=self.owner, role=Roster.Role.CAPTAIN)
        Roster.objects.create(team=mine, player=self.viewer)
        self.client.force_login(self.viewer)

    def test_shows_name_and_teams(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alex Lee")
        self.assertContains(response, "Violets")
        self.assertContains(response, "Bobcats")

    def test_email_is_not_shown_to_other_players(self):
        self.assertNotContains(self.client.get(self.url), "owner@nyu.edu")

    def test_n_number_and_net_id_hidden_from_others(self):
        response = self.client.get(self.url)
        self.assertNotContains(response, "N12345678")
        self.assertNotContains(response, "al1234")
        self.assertNotContains(response, reverse("profiles:edit", args=[self.owner.pk]))

    def test_owner_sees_own_details_and_edit_link(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.url)
        self.assertContains(response, "N12345678")
        self.assertContains(response, "al1234")
        self.assertContains(response, reverse("profiles:edit", args=[self.owner.pk]))

    def test_only_shared_teams_are_links(self):
        response = self.client.get(self.url)
        self.assertContains(response, reverse("teams:detail", args=[self.shared.pk]))
        other = self.owner.roster_entries.exclude(team=self.shared).get().team
        self.assertNotContains(response, reverse("teams:detail", args=[other.pk]))

    def test_player_without_teams(self):
        response = self.client.get(reverse("profiles:detail", args=[self.viewer.pk]))
        self.assertContains(response, "Violets")
        loner = make_user("loner")
        response = self.client.get(reverse("profiles:detail", args=[loner.pk]))
        self.assertContains(response, "Not on any teams yet.")

    def test_unknown_or_unverified_player_is_404(self):
        self.assertEqual(self.client.get(reverse("profiles:detail", args=[99999])).status_code, 404)
        pending = make_user("pending")
        pending.is_active = False
        pending.save()
        self.assertEqual(self.client.get(reverse("profiles:detail", args=[pending.pk])).status_code, 404)

    def test_signed_out_user_is_sent_to_login(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_roster_links_to_player_profiles(self):
        response = self.client.get(reverse("teams:detail", args=[self.shared.pk]))
        self.assertContains(response, self.url)

    def test_saving_edit_goes_to_profile_page(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("profiles:edit", args=[self.owner.pk]),
            {"first_name": "Sam", "last_name": "Park", "n_number": "N87654321", "net_id": "sp9876"},
        )
        self.assertRedirects(response, self.url)


class CreateProfileTests(TestCase):
    def setUp(self):
        self.user = make_user("newcomer")
        self.url = reverse("profiles:create")
        self.client.force_login(self.user)

    def test_form_is_shown_with_name_prefilled(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<h1>Create profile</h1>", html=True)
        self.assertContains(response, 'value="Alex"')
        self.assertContains(response, 'name="n_number"')
        self.assertContains(response, 'name="net_id"')

    def test_valid_profile_is_created_and_saved(self):
        response = self.client.post(self.url, VALID, follow=True)
        profile = PlayerProfile.objects.get(user=self.user)
        self.user.refresh_from_db()
        self.assertEqual(
            (self.user.first_name, self.user.last_name, profile.n_number, profile.net_id),
            ("Sam", "Park", "N87654321", "sp9876"),
        )
        self.assertContains(response, "Your profile has been created.")

    def test_valid_create_redirects_so_refresh_does_not_resubmit(self):
        response = self.client.post(self.url, VALID)
        self.assertEqual(response.status_code, 302)

    def test_invalid_create_saves_nothing(self):
        response = self.client.post(self.url, {**VALID, "n_number": "123"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your profile was not created.")
        self.assertContains(response, "N followed by 8 digits")
        self.assertFalse(PlayerProfile.objects.filter(user=self.user).exists())
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Alex")

    def test_duplicate_net_id_rejected(self):
        make_user("other", n_number="N11111111", net_id="sp9876")
        response = self.client.post(self.url, VALID)
        self.assertContains(response, "This NetID is already used by another account.")
        self.assertFalse(PlayerProfile.objects.filter(user=self.user).exists())

    def test_existing_profile_redirects_to_edit(self):
        PlayerProfile.objects.create(user=self.user, n_number="N12345678", net_id="al1234")
        response = self.client.post(self.url, VALID)
        self.assertRedirects(response, reverse("profiles:edit", args=[self.user.pk]))
        self.assertEqual(PlayerProfile.objects.get(user=self.user).net_id, "al1234")

    def test_signed_out_user_is_sent_to_login(self):
        self.client.logout()
        response = self.client.post(self.url, VALID)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)
        self.assertFalse(PlayerProfile.objects.exists())

    def test_nav_shows_my_profile_and_edit_leads_to_create(self):
        response = self.client.get(reverse("teams:list"))
        self.assertContains(response, reverse("profiles:detail", args=[self.user.pk]))
        response = self.client.get(reverse("profiles:edit", args=[self.user.pk]))
        self.assertRedirects(response, self.url)
