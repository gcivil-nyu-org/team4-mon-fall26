from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


# TODO(T10): switch to the shared fixtures once they land.
def make_user(username, first_name="Alex", last_name="Lee"):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@nyu.edu",
        password="pass12345!",
        first_name=first_name,
        last_name=last_name,
    )


class EditProfileTests(TestCase):
    def setUp(self):
        self.user = make_user("owner")
        self.url = reverse("profiles:edit", args=[self.user.pk])
        self.client.force_login(self.user)

    def test_form_shows_current_values(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="Alex"')
        self.assertContains(response, 'value="Lee"')

    def test_email_is_not_on_the_form(self):
        response = self.client.get(self.url)
        self.assertNotContains(response, 'name="email"')

    def test_valid_update_is_saved(self):
        response = self.client.post(self.url, {"first_name": "Sam", "last_name": "Park"}, follow=True)
        self.user.refresh_from_db()
        self.assertEqual((self.user.first_name, self.user.last_name), ("Sam", "Park"))
        self.assertContains(response, "Your profile has been updated.")

    def test_valid_update_redirects_so_refresh_does_not_resubmit(self):
        response = self.client.post(self.url, {"first_name": "Sam", "last_name": "Park"})
        self.assertEqual(response.status_code, 302)

    def test_email_cannot_be_changed(self):
        self.client.post(
            self.url, {"first_name": "Sam", "last_name": "Park", "email": "new@nyu.edu"}
        )
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "owner@nyu.edu")

    def test_rejected_update_shows_errors_and_saves_nothing(self):
        response = self.client.post(self.url, {"first_name": "   ", "last_name": "Park"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required.")
        self.assertContains(response, "Your profile was not updated.")
        self.assertNotContains(response, "Your profile has been updated.")
        self.user.refresh_from_db()
        self.assertEqual((self.user.first_name, self.user.last_name), ("Alex", "Lee"))

    def test_rejected_update_keeps_entered_values(self):
        response = self.client.post(self.url, {"first_name": "", "last_name": "Park"})
        self.assertContains(response, 'value="Park"')

    def test_too_long_value_rejected(self):
        response = self.client.post(self.url, {"first_name": "x" * 151, "last_name": "Park"})
        self.assertContains(response, "Ensure this value has at most 150 characters")
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Alex")

    def test_retry_after_rejection_is_saved(self):
        self.client.post(self.url, {"first_name": "", "last_name": "Park"})
        response = self.client.post(self.url, {"first_name": "Sam", "last_name": "Park"})
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual((self.user.first_name, self.user.last_name), ("Sam", "Park"))

    def test_other_users_profile_is_forbidden(self):
        other = make_user("other", first_name="Jo", last_name="Kim")
        url = reverse("profiles:edit", args=[other.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        response = self.client.post(url, {"first_name": "Hacked", "last_name": "Name"})
        self.assertEqual(response.status_code, 403)
        other.refresh_from_db()
        self.assertEqual(other.first_name, "Jo")

    def test_missing_user_is_404(self):
        response = self.client.get(reverse("profiles:edit", args=[99999]))
        self.assertEqual(response.status_code, 404)

    def test_signed_out_user_is_sent_to_login(self):
        self.client.logout()
        response = self.client.post(self.url, {"first_name": "Sam", "last_name": "Park"})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Alex")

    def test_nav_links_to_edit_profile(self):
        response = self.client.get(reverse("teams:list"))
        self.assertContains(response, self.url)
