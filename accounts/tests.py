from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

VALID = {
    "email": "Sam.Park@NYU.edu",
    "first_name": "Sam",
    "last_name": "Park",
    "password1": "Str0ng-pass-2026",
    "password2": "Str0ng-pass-2026",
}


class SignUpTests(TestCase):
    url = reverse("accounts:signup")

    def test_page_loads(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="email"')

    def test_valid_signup_creates_user_logs_in_and_goes_to_create_profile(self):
        response = self.client.post(self.url, VALID)
        self.assertRedirects(response, reverse("profiles:create"))
        user = get_user_model().objects.get(email="sam.park@nyu.edu")
        self.assertEqual(user.username, "sam.park@nyu.edu")
        self.assertEqual((user.first_name, user.last_name), ("Sam", "Park"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_can_log_in_with_email_afterwards(self):
        self.client.post(self.url, VALID)
        self.client.logout()
        logged_in = self.client.login(username="sam.park@nyu.edu", password=VALID["password1"])
        self.assertTrue(logged_in)

    def test_non_nyu_email_rejected(self):
        response = self.client.post(self.url, {**VALID, "email": "sam@gmail.com"})
        self.assertContains(response, "Please use your NYU ID")
        self.assertFalse(get_user_model().objects.exists())

    def test_duplicate_email_rejected(self):
        get_user_model().objects.create_user("sam.park@nyu.edu", "sam.park@nyu.edu", "x-pass-12345")
        response = self.client.post(self.url, VALID)
        self.assertContains(response, "An account with this email already exists.")
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_password_mismatch_rejected(self):
        response = self.client.post(self.url, {**VALID, "password2": "different-pass-1"})
        self.assertContains(response, "Your account was not created.")
        self.assertFalse(get_user_model().objects.exists())

    def test_weak_password_rejected(self):
        response = self.client.post(self.url, {**VALID, "password1": "123", "password2": "123"})
        self.assertContains(response, "Your account was not created.")
        self.assertFalse(get_user_model().objects.exists())

    def test_signed_in_user_is_redirected(self):
        user = get_user_model().objects.create_user("a@nyu.edu", "a@nyu.edu", "x-pass-12345")
        self.client.force_login(user)
        self.assertRedirects(self.client.get(self.url), reverse("teams:list"))

    def test_nav_and_login_page_link_to_signup(self):
        self.assertContains(self.client.get(reverse("login")), self.url)
