from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import TestCase


class ProfileUrlTagTests(TestCase):
    def test_links_to_the_profile_page(self):
        user = get_user_model().objects.create_user(
            username="alex", email="alex@nyu.edu", password="pass12345!"
        )
        rendered = Template("{% load teams_extras %}{% profile_url user %}").render(
            Context({"user": user})
        )
        self.assertEqual(rendered, f"/profiles/{user.pk}/")
