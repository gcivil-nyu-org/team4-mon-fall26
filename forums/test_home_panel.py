from datetime import timedelta

from django.contrib.auth.models import AnonymousUser
from django.template import Context, Template
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from teams.models import Sport

from .models import Reply, Topic
from .templatetags.forum_tags import HOME_PANEL_SIZE, home_forum_panel
from .tests import make_topic, make_user

PANEL = Template("{% load forum_tags %}{% home_forum_panel %}")


def render_panel(user):
    return PANEL.render(Context({"user": user}))


def make_topics_by_age(author, count):
    """Topics "Topic 0" (newest activity) to "Topic count-1" (oldest)."""
    now = timezone.now()
    return [
        make_topic(
            author,
            title=f"Topic {index}",
            last_activity_at=now - timedelta(hours=index + 1),
        )
        for index in range(count)
    ]


class HomeForumPanelTests(TestCase):
    def setUp(self):
        self.user = make_user("player")

    def test_shows_five_topics_newest_activity_first(self):
        make_topics_by_age(self.user, HOME_PANEL_SIZE + 2)
        data = home_forum_panel({"user": self.user})
        self.assertTrue(data["show"])
        self.assertEqual(
            [topic.title for topic in data["topics"]],
            [f"Topic {index}" for index in range(HOME_PANEL_SIZE)],
        )
        html = render_panel(self.user)
        self.assertNotIn("Topic 5", html)
        self.assertLess(html.index("Topic 0"), html.index("Topic 4"))

    def test_reply_moves_topic_to_the_top(self):
        topics = make_topics_by_age(self.user, 3)
        Reply.objects.create(topic=topics[2], author=self.user, body="Bump")
        data = home_forum_panel({"user": self.user})
        self.assertEqual(data["topics"][0].pk, topics[2].pk)

    def test_row_shows_sport_or_general(self):
        soccer = Sport.objects.create(name="Soccer")
        make_topic(self.user, title="Sport topic", sport=soccer)
        make_topic(self.user, title="Open topic")
        labels = {
            topic.title: topic.sport_label
            for topic in home_forum_panel({"user": self.user})["topics"]
        }
        self.assertEqual(labels, {"Sport topic": "Soccer", "Open topic": "General"})
        html = render_panel(self.user)
        self.assertIn("Soccer ·", html)
        self.assertIn("General ·", html)

    def test_reply_count_is_pluralised(self):
        for title, replies in (("None", 0), ("One", 1), ("Two", 2)):
            topic = make_topic(self.user, title=title)
            for _ in range(replies):
                Reply.objects.create(topic=topic, author=self.user, body="Me too")
        html = render_panel(self.user)
        self.assertIn('<span class="pn-num">0</span> replies ·', html)
        self.assertIn('<span class="pn-num">1</span> reply ·', html)
        self.assertIn('<span class="pn-num">2</span> replies ·', html)

    def test_row_shows_relative_time(self):
        make_topic(self.user, title="Fresh")
        make_topic(
            self.user,
            title="Old",
            last_activity_at=timezone.now() - timedelta(hours=3, minutes=20),
        )
        html = render_panel(self.user)
        self.assertIn("Just now", html)
        self.assertIn("3\xa0hours ago", html)
        self.assertNotIn("minutes", html)

    def test_rows_and_header_link_to_the_forum(self):
        topic = make_topic(self.user)
        html = render_panel(self.user)
        self.assertIn(f'href="{reverse("forums:detail", args=[topic.pk])}"', html)
        self.assertIn(f'href="{reverse("forums:list")}"', html)
        self.assertIn("All topics", html)
        self.assertIn("text-truncate", html)
        self.assertNotIn("No topics yet", html)

    def test_title_is_escaped(self):
        make_topic(self.user, title="<b>Bold</b>")
        html = render_panel(self.user)
        self.assertIn("&lt;b&gt;Bold&lt;/b&gt;", html)
        self.assertNotIn("<b>Bold</b>", html)

    def test_flagged_topic_stays_in_the_panel(self):
        make_topic(self.user, title="Reported topic", is_flagged=True)
        self.assertIn("Reported topic", render_panel(self.user))

    def test_empty_state_links_to_new_topic(self):
        html = render_panel(self.user)
        self.assertIn("No topics yet. Start the first one.", html)
        self.assertIn(f'href="{reverse("forums:create")}"', html)
        self.assertIn(f'href="{reverse("forums:list")}"', html)
        self.assertIn("btn-outline-secondary", html)
        self.assertNotIn("btn-primary", html)
        self.assertNotIn("list-group", html)

    def test_renders_nothing_for_anonymous_user(self):
        make_topic(self.user)
        with self.assertNumQueries(0):
            self.assertEqual(render_panel(AnonymousUser()).strip(), "")
            self.assertEqual(PANEL.render(Context({})).strip(), "")

    def test_uses_one_query(self):
        soccer = Sport.objects.create(name="Soccer")
        for topic in make_topics_by_age(self.user, HOME_PANEL_SIZE + 1):
            Topic.objects.filter(pk=topic.pk).update(sport=soccer)
            replier = make_user(f"replier{topic.pk}")
            Reply.objects.create(topic=topic, author=replier, body="Me too")
        with self.assertNumQueries(1):
            render_panel(self.user)

    def test_empty_panel_uses_one_query(self):
        with self.assertNumQueries(1):
            render_panel(self.user)


class DashboardForumPanelTests(TestCase):
    def setUp(self):
        self.user = make_user("player")
        self.client.force_login(self.user)

    def test_dashboard_renders_the_panel(self):
        topic = make_topic(self.user, title="Dashboard topic")
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "forums/_home_panel.html")
        self.assertContains(response, "Dashboard topic")
        self.assertContains(response, reverse("forums:detail", args=[topic.pk]))
        self.assertContains(response, "All topics")
        self.assertNotContains(response, "slot: forum")

    def test_dashboard_renders_the_empty_state(self):
        response = self.client.get(reverse("core:home"))
        self.assertContains(response, "No topics yet. Start the first one.")
        self.assertContains(response, reverse("forums:create"))
