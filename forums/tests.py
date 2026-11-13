from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.roles import LEAGUE_ADMIN_ROLE, assign_role
from audit.models import AuditLog
from teams.models import Sport

from .models import Reply, Topic
from .selectors import latest_topics
from .views import TOPICS_PER_PAGE


def make_user(username):
    return get_user_model().objects.create_user(
        username=username, email=f"{username}@nyu.edu", password="pass12345!"
    )


def make_admin(username="admin"):
    user = make_user(username)
    assign_role(user, LEAGUE_ADMIN_ROLE)
    return user


def make_topic(author, title="Pickup soccer on Friday", sport=None, **kwargs):
    return Topic.objects.create(
        author=author, title=title, body="Who is in?", sport=sport, **kwargs
    )


class ModelTests(TestCase):
    def setUp(self):
        self.user = make_user("player")

    def test_new_topic_sets_last_activity_and_is_not_flagged(self):
        before = timezone.now()
        topic = make_topic(self.user)
        self.assertGreaterEqual(topic.last_activity_at, before)
        self.assertFalse(topic.is_flagged)
        self.assertEqual(str(topic), "Pickup soccer on Friday")

    def test_reply_bumps_topic_last_activity(self):
        old = timezone.now() - timedelta(days=3)
        topic = make_topic(self.user, last_activity_at=old)
        reply = Reply.objects.create(topic=topic, author=self.user, body="I am in")
        topic.refresh_from_db()
        self.assertEqual(topic.last_activity_at, reply.created_at)
        self.assertFalse(reply.is_flagged)
        self.assertIn("I am in", str(reply))

    def test_reply_edit_does_not_bump_last_activity(self):
        topic = make_topic(self.user)
        reply = Reply.objects.create(topic=topic, author=self.user, body="I am in")
        old = timezone.now() - timedelta(days=3)
        Topic.objects.filter(pk=topic.pk).update(last_activity_at=old)
        reply.is_flagged = True
        reply.save()
        topic.refresh_from_db()
        self.assertEqual(topic.last_activity_at, old)

    def test_reply_moves_topic_to_the_top(self):
        now = timezone.now()
        older = make_topic(self.user, "Older", last_activity_at=now - timedelta(days=2))
        newer = make_topic(self.user, "Newer", last_activity_at=now - timedelta(days=1))
        self.assertEqual(list(Topic.objects.all()), [newer, older])
        Reply.objects.create(topic=older, author=self.user, body="Bump")
        self.assertEqual(list(Topic.objects.all()), [older, newer])

    def test_deleted_sport_moves_topic_to_general(self):
        sport = Sport.objects.create(name="Soccer")
        topic = make_topic(self.user, sport=sport)
        self.assertEqual(topic.sport_label, "Soccer")
        sport.delete()
        topic.refresh_from_db()
        self.assertIsNone(topic.sport)
        self.assertEqual(topic.sport_label, "General")

    def test_deleted_topic_deletes_its_replies(self):
        topic = make_topic(self.user)
        Reply.objects.create(topic=topic, author=self.user, body="I am in")
        topic.delete()
        self.assertFalse(Reply.objects.exists())


class SelectorTests(TestCase):
    def test_latest_topics_are_limited_ordered_and_counted(self):
        user = make_user("player")
        now = timezone.now()
        topics = [
            make_topic(user, f"Topic {n}", last_activity_at=now - timedelta(hours=n))
            for n in range(7)
        ]
        Reply.objects.create(topic=topics[6], author=user, body="One")
        Reply.objects.create(topic=topics[6], author=user, body="Two")

        latest = list(latest_topics())
        self.assertEqual(len(latest), 5)
        self.assertEqual(latest[0], topics[6])
        self.assertEqual(latest[0].reply_count, 2)
        self.assertEqual(latest[1], topics[0])
        self.assertEqual(latest[1].reply_count, 0)
        self.assertEqual(len(latest_topics(limit=2)), 2)


class PermissionTests(TestCase):
    def setUp(self):
        self.author = make_user("author")
        self.other = make_user("other")
        self.admin = make_admin()
        self.topic = make_topic(self.author)
        self.reply = Reply.objects.create(
            topic=self.topic, author=self.other, body="I am in"
        )
        self.delete_topic_url = reverse("forums:delete_topic", args=[self.topic.pk])
        self.delete_reply_url = reverse(
            "forums:delete_reply", args=[self.topic.pk, self.reply.pk]
        )

    def test_anonymous_redirected_to_login_on_every_page(self):
        urls = [
            reverse("forums:list"),
            reverse("forums:create"),
            reverse("forums:detail", args=[self.topic.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn("/accounts/login/", response["Location"])

    def test_anonymous_cannot_post_or_delete(self):
        self.client.post(
            reverse("forums:create"), {"title": "Hello", "body": "Anyone there?"}
        )
        self.client.post(
            reverse("forums:detail", args=[self.topic.pk]), {"body": "Me too"}
        )
        response = self.client.post(self.delete_topic_url)
        self.assertIn("/accounts/login/", response["Location"])
        self.assertEqual(Topic.objects.count(), 1)
        self.assertEqual(Reply.objects.count(), 1)

    def test_any_signed_in_user_reads_another_users_topic(self):
        self.client.force_login(self.other)
        response = self.client.get(reverse("forums:detail", args=[self.topic.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Delete topic")
        self.assertNotContains(response, self.delete_reply_url)

    def test_admin_deletes_topic_with_its_replies(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.delete_topic_url)
        self.assertRedirects(response, reverse("forums:list"))
        self.assertFalse(Topic.objects.exists())
        self.assertFalse(Reply.objects.exists())
        entry = AuditLog.objects.get(object_type="Topic")
        self.assertEqual(entry.actor, self.admin)
        self.assertEqual(entry.action, AuditLog.Action.DELETED)
        self.assertEqual(entry.object_id, str(self.topic.pk))

    def test_admin_deletes_reply_and_keeps_topic(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.delete_reply_url)
        self.assertRedirects(response, reverse("forums:detail", args=[self.topic.pk]))
        self.assertFalse(Reply.objects.exists())
        self.assertTrue(Topic.objects.filter(pk=self.topic.pk).exists())
        self.assertTrue(AuditLog.objects.filter(object_type="Reply").exists())

    def test_superuser_deletes_topic(self):
        root = get_user_model().objects.create_superuser(
            username="root", email="root@nyu.edu", password="pass12345!"
        )
        self.client.force_login(root)
        self.client.post(self.delete_topic_url)
        self.assertFalse(Topic.objects.exists())

    def test_admin_sees_delete_controls_with_confirmation(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("forums:detail", args=[self.topic.pk]))
        self.assertContains(response, self.delete_topic_url)
        self.assertContains(response, self.delete_reply_url)
        self.assertContains(response, "return confirm(", count=2)

    def test_non_admin_delete_is_403_even_for_the_author(self):
        for user in (self.author, self.other):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                self.assertEqual(
                    self.client.post(self.delete_topic_url).status_code, 403
                )
                self.assertEqual(
                    self.client.post(self.delete_reply_url).status_code, 403
                )
        self.assertEqual(Topic.objects.count(), 1)
        self.assertEqual(Reply.objects.count(), 1)
        self.assertFalse(AuditLog.objects.filter(object_type="Topic").exists())

    def test_delete_needs_post(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.delete_topic_url).status_code, 405)
        self.assertEqual(self.client.get(self.delete_reply_url).status_code, 405)
        self.assertEqual(Topic.objects.count(), 1)

    def test_reply_delete_needs_the_replys_own_topic(self):
        elsewhere = make_topic(self.author, "Another topic")
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("forums:delete_reply", args=[elsewhere.pk, self.reply.pk])
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Reply.objects.count(), 1)


class TopicListTests(TestCase):
    def setUp(self):
        self.user = make_user("player")
        self.client.force_login(self.user)
        self.url = reverse("forums:list")

    def test_empty_state(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No topics yet")
        self.assertContains(response, 'class="empty"')

    def test_one_primary_button(self):
        make_topic(self.user)
        response = self.client.get(self.url)
        self.assertContains(response, "btn-primary", count=1)

    def test_topics_ordered_by_last_activity_with_reply_counts(self):
        now = timezone.now()
        quiet = make_topic(self.user, "Quiet", last_activity_at=now - timedelta(days=1))
        busy = make_topic(self.user, "Busy", last_activity_at=now - timedelta(days=2))
        Reply.objects.create(topic=busy, author=self.user, body="Bump")
        response = self.client.get(self.url)
        topics = list(response.context["page_obj"])
        self.assertEqual(topics, [busy, quiet])
        self.assertEqual(topics[0].reply_count, 1)
        self.assertEqual(topics[1].reply_count, 0)
        self.assertContains(response, reverse("forums:detail", args=[busy.pk]))

    def test_filter_by_sport_and_general(self):
        soccer = Sport.objects.create(name="Soccer")
        tennis = Sport.objects.create(name="Tennis")
        make_topic(self.user, "Soccer talk", sport=soccer)
        make_topic(self.user, "Tennis talk", sport=tennis)
        make_topic(self.user, "Anything goes")

        def titles(query):
            page = self.client.get(self.url, query).context["page_obj"]
            return sorted(topic.title for topic in page)

        self.assertEqual(titles({"sport": soccer.pk}), ["Soccer talk"])
        self.assertEqual(titles({"sport": "general"}), ["Anything goes"])
        self.assertEqual(len(titles({})), 3)
        # An unknown filter shows every topic.
        self.assertEqual(len(titles({"sport": "999999"})), 3)
        self.assertEqual(len(titles({"sport": "nonsense"})), 3)

    def test_filter_offers_general_and_every_sport(self):
        Sport.objects.create(name="Soccer")
        response = self.client.get(self.url)
        self.assertContains(response, '<option value="general">General</option>')
        self.assertContains(response, "Soccer</option>")

    def test_filtered_empty_state(self):
        soccer = Sport.objects.create(name="Soccer")
        make_topic(self.user, "Anything goes")
        response = self.client.get(self.url, {"sport": soccer.pk})
        self.assertContains(response, "No Soccer topics yet")
        response = self.client.get(self.url, {"sport": "general"})
        self.assertNotContains(response, 'class="empty"')

    def test_pagination_keeps_the_filter(self):
        soccer = Sport.objects.create(name="Soccer")
        for n in range(TOPICS_PER_PAGE + 1):
            make_topic(self.user, f"Topic {n}", sport=soccer)
        first = self.client.get(self.url, {"sport": soccer.pk})
        self.assertEqual(len(first.context["page_obj"]), TOPICS_PER_PAGE)
        self.assertContains(first, f"?sport={soccer.pk}&amp;page=2")
        second = self.client.get(self.url, {"sport": soccer.pk, "page": 2})
        self.assertEqual(len(second.context["page_obj"]), 1)
        self.assertContains(second, f"?sport={soccer.pk}&amp;page=1")

    def test_no_pager_on_a_single_page(self):
        make_topic(self.user)
        self.assertNotContains(self.client.get(self.url), "pagination")

    def test_navbar_highlights_forum(self):
        response = self.client.get(self.url)
        self.assertContains(
            response,
            f'<a class="nav-link" href="{self.url}" aria-current="page">',
        )
        home = self.client.get(reverse("core:home"))
        self.assertContains(home, f'<a class="nav-link" href="{self.url}">')


class TopicCreateTests(TestCase):
    def setUp(self):
        self.user = make_user("player")
        self.client.force_login(self.user)
        self.url = reverse("forums:create")

    def test_form_offers_general_and_sports(self):
        Sport.objects.create(name="Soccer")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, ">General</option>")
        self.assertContains(response, ">Soccer</option>")
        self.assertContains(response, "btn-primary", count=1)

    def test_create_general_topic(self):
        response = self.client.post(
            self.url, {"sport": "", "title": "  Hello  ", "body": "  Anyone there?  "}
        )
        topic = Topic.objects.get()
        self.assertRedirects(response, reverse("forums:detail", args=[topic.pk]))
        self.assertEqual(topic.title, "Hello")
        self.assertEqual(topic.body, "Anyone there?")
        self.assertEqual(topic.author, self.user)
        self.assertIsNone(topic.sport)
        self.assertFalse(topic.is_flagged)

    def test_create_sport_topic(self):
        soccer = Sport.objects.create(name="Soccer")
        self.client.post(
            self.url, {"sport": soccer.pk, "title": "Hello", "body": "Anyone there?"}
        )
        self.assertEqual(Topic.objects.get().sport, soccer)

    def test_whitespace_only_title_or_body_rejected(self):
        for data in (
            {"title": "   ", "body": "Anyone there?"},
            {"title": "Hello", "body": " \n\t "},
        ):
            with self.subTest(data=data):
                response = self.client.post(self.url, data)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)
        self.assertFalse(Topic.objects.exists())

    def test_length_limits(self):
        response = self.client.post(self.url, {"title": "t" * 121, "body": "Body"})
        self.assertIn("title", response.context["form"].errors)
        response = self.client.post(self.url, {"title": "Title", "body": "b" * 2001})
        self.assertIn("body", response.context["form"].errors)
        self.assertFalse(Topic.objects.exists())

        self.client.post(self.url, {"title": "t" * 120, "body": "b" * 2000})
        topic = Topic.objects.get()
        self.assertEqual(len(topic.title), 120)
        self.assertEqual(len(topic.body), 2000)

    def test_unknown_sport_rejected(self):
        response = self.client.post(
            self.url, {"sport": "999999", "title": "Hello", "body": "Anyone there?"}
        )
        self.assertIn("sport", response.context["form"].errors)
        self.assertFalse(Topic.objects.exists())


class TopicDetailTests(TestCase):
    def setUp(self):
        self.author = make_user("author")
        self.user = make_user("player")
        self.topic = make_topic(self.author)
        self.url = reverse("forums:detail", args=[self.topic.pk])
        self.client.force_login(self.user)

    def test_shows_topic_and_reply_empty_state(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Pickup soccer on Friday")
        self.assertContains(response, "Who is in?")
        self.assertContains(response, "author@nyu.edu")
        self.assertContains(response, "No replies yet")
        self.assertContains(response, "btn-primary", count=1)
        self.assertContains(response, "rounded-circle")

    def test_missing_topic_is_404(self):
        response = self.client.get(reverse("forums:detail", args=[self.topic.pk + 1]))
        self.assertEqual(response.status_code, 404)

    def test_replies_oldest_first(self):
        now = timezone.now()
        second = Reply.objects.create(topic=self.topic, author=self.user, body="Two")
        first = Reply.objects.create(topic=self.topic, author=self.author, body="One")
        Reply.objects.filter(pk=first.pk).update(created_at=now - timedelta(hours=1))
        response = self.client.get(self.url)
        self.assertEqual(list(response.context["replies"]), [first, second])
        self.assertNotContains(response, "No replies yet")

    def test_reply_posts_and_bumps_topic(self):
        old = timezone.now() - timedelta(days=1)
        Topic.objects.filter(pk=self.topic.pk).update(last_activity_at=old)
        response = self.client.post(self.url, {"body": "  I am in  "})
        self.assertRedirects(response, self.url)
        reply = Reply.objects.get()
        self.assertEqual(reply.body, "I am in")
        self.assertEqual(reply.author, self.user)
        self.assertEqual(reply.topic, self.topic)
        self.topic.refresh_from_db()
        self.assertGreater(self.topic.last_activity_at, old)

    def test_whitespace_only_reply_rejected(self):
        response = self.client.post(self.url, {"body": "   "})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertFalse(Reply.objects.exists())

    def test_reply_length_limit(self):
        response = self.client.post(self.url, {"body": "b" * 1001})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Reply.objects.exists())
        self.client.post(self.url, {"body": "b" * 1000})
        self.assertEqual(len(Reply.objects.get().body), 1000)

    def test_post_body_is_escaped(self):
        Reply.objects.create(
            topic=self.topic, author=self.user, body="<script>alert(1)</script>"
        )
        response = self.client.get(self.url)
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;")

    def test_no_report_ui_yet(self):
        Reply.objects.create(topic=self.topic, author=self.author, body="One")
        self.assertNotContains(self.client.get(self.url), "Report")
