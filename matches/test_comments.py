"""Match comments (#170): post, report, and League Admin moderation."""

import datetime

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from audit.models import AuditLog
from chat.moderation import flagged_total
from teams.models import Season
from teams.season_rules import SeasonState

from .models import MatchComment
from .tests import MatchFixtures, make_user


class MatchCommentFixtures(MatchFixtures):
    def setUp(self):
        self.match = self.build()
        self.match.save()
        self.other = make_user("other")

    def detail_url(self, match=None):
        return reverse("matches:detail", args=[(match or self.match).pk])

    def comment(self, body="Great game", author=None, match=None, **extra):
        return MatchComment.objects.create(
            match=match or self.match, author=author or self.other, body=body, **extra
        )

    def report_url(self, comment):
        return reverse("matches:report_comment", args=[comment.match_id, comment.pk])

    def delete_url(self, comment):
        return reverse("matches:delete_comment", args=[comment.match_id, comment.pk])

    def moderate_url(self, comment):
        return reverse("matches:moderate_comment", args=[comment.pk])

    def draft_match(self):
        draft = Season.objects.create(
            name="Draft", start_date=datetime.date(2027, 3, 1), state=SeasonState.DRAFT
        )
        match = self.build(season=draft)
        match.save()
        return match


class PostCommentTests(MatchCommentFixtures):
    def test_anonymous_cannot_post(self):
        response = self.client.post(self.detail_url(), {"body": "Hi"})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)
        self.assertFalse(MatchComment.objects.exists())

    def test_player_posts_a_comment(self):
        self.client.force_login(self.player)
        response = self.client.post(self.detail_url(), {"body": "  Close one!  "})
        self.assertRedirects(response, self.detail_url() + "#comments")
        comment = MatchComment.objects.get()
        self.assertEqual(comment.author, self.player)
        self.assertEqual(comment.match, self.match)
        self.assertEqual(comment.body, "Close one!")
        self.assertFalse(comment.is_flagged)

    def test_page_lists_comments_oldest_first(self):
        first = self.comment("First")
        second = self.comment("Second", author=self.player)
        self.client.force_login(self.player)
        response = self.client.get(self.detail_url())
        self.assertEqual(list(response.context["comments"]), [first, second])
        self.assertContains(response, 'id="comments"')
        self.assertContains(response, self.report_url(first))
        self.assertNotContains(response, "No comments yet")

    def test_empty_state(self):
        self.client.force_login(self.player)
        self.assertContains(self.client.get(self.detail_url()), "No comments yet")

    def test_blank_comment_is_rejected(self):
        self.client.force_login(self.player)
        response = self.client.post(self.detail_url(), {"body": "   "})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["comment_form"].errors["body"])
        self.assertFalse(MatchComment.objects.exists())

    def test_long_comment_is_rejected(self):
        self.client.force_login(self.player)
        body = "x" * (MatchComment.MAX_BODY_LENGTH + 1)
        response = self.client.post(self.detail_url(), {"body": body})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["comment_form"].errors["body"])
        self.assertFalse(MatchComment.objects.exists())

    def test_player_cannot_post_on_a_draft_season_match(self):
        match = self.draft_match()
        self.client.force_login(self.player)
        response = self.client.post(self.detail_url(match), {"body": "Hi"})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(MatchComment.objects.exists())

    def test_comment_text_is_escaped(self):
        self.comment("<script>alert(1)</script>")
        self.client.force_login(self.player)
        response = self.client.get(self.detail_url())
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, "&lt;script&gt;")

    def test_query_count_does_not_grow_with_comments(self):
        self.comment("One")
        self.client.force_login(self.player)
        with CaptureQueriesContext(connection) as captured:
            self.client.get(self.detail_url())
        for i in range(5):
            self.comment(f"More {i}", author=make_user(f"fan{i}"))
        with self.assertNumQueries(len(captured)):
            self.client.get(self.detail_url())

    def test_str(self):
        self.other.first_name, self.other.last_name = "Sam", "Kim"
        self.other.save()
        self.assertEqual(
            str(self.comment("Nice")), "Sam Kim on Violets vs Bobcats: Nice"
        )


class ReportCommentTests(MatchCommentFixtures):
    def test_anonymous_cannot_report(self):
        comment = self.comment()
        self.assertEqual(self.client.post(self.report_url(comment)).status_code, 302)
        comment.refresh_from_db()
        self.assertFalse(comment.is_flagged)

    def test_report_needs_post(self):
        self.client.force_login(self.player)
        response = self.client.get(self.report_url(self.comment()))
        self.assertEqual(response.status_code, 405)

    def test_player_reports_a_comment(self):
        comment = self.comment()
        self.client.force_login(self.player)
        response = self.client.post(self.report_url(comment), follow=True)
        self.assertRedirects(response, self.detail_url() + "#comments")
        self.assertContains(response, "Comment reported for League Admin review.")
        self.assertContains(response, "Reported")
        self.assertNotContains(response, self.report_url(comment))
        comment.refresh_from_db()
        self.assertTrue(comment.is_flagged)

    def test_second_report_changes_nothing(self):
        comment = self.comment(is_flagged=True)
        self.client.force_login(self.player)
        self.client.post(self.report_url(comment))
        comment.refresh_from_db()
        self.assertTrue(comment.is_flagged)

    def test_comment_must_belong_to_the_match(self):
        comment = self.comment()
        other_match = self.build(
            starts_at=self.match.ends_at,
            ends_at=self.match.ends_at + datetime.timedelta(hours=1),
        )
        other_match.save()
        self.client.force_login(self.player)
        url = reverse("matches:report_comment", args=[other_match.pk, comment.pk])
        self.assertEqual(self.client.post(url).status_code, 404)

    def test_player_cannot_report_on_a_draft_season_match(self):
        comment = self.comment(match=self.draft_match())
        self.client.force_login(self.player)
        self.assertEqual(self.client.post(self.report_url(comment)).status_code, 404)


class DeleteCommentTests(MatchCommentFixtures):
    def test_player_cannot_delete(self):
        comment = self.comment()
        self.client.force_login(self.player)
        self.assertEqual(self.client.post(self.delete_url(comment)).status_code, 403)
        self.assertTrue(MatchComment.objects.filter(pk=comment.pk).exists())

    def test_only_admins_see_delete(self):
        comment = self.comment()
        self.client.force_login(self.player)
        self.assertNotContains(
            self.client.get(self.detail_url()), self.delete_url(comment)
        )
        self.client.force_login(self.admin)
        self.assertContains(
            self.client.get(self.detail_url()), self.delete_url(comment)
        )

    def test_admin_deletes_and_it_is_audited(self):
        comment = self.comment()
        self.client.force_login(self.admin)
        response = self.client.post(self.delete_url(comment))
        self.assertRedirects(response, self.detail_url() + "#comments")
        self.assertFalse(MatchComment.objects.exists())
        log = AuditLog.objects.get(object_type="MatchComment")
        self.assertEqual(log.actor, self.admin)
        self.assertEqual(log.action, AuditLog.Action.DELETED)
        self.assertEqual(log.object_type, "MatchComment")
        self.assertEqual(log.object_id, str(comment.pk))


class ModerateCommentTests(MatchCommentFixtures):
    def queue(self):
        return self.client.get(reverse("chat:moderation_queue"))

    def test_flagged_comments_show_in_the_queue(self):
        flagged = self.comment("Rude", is_flagged=True)
        self.comment("Fine")
        self.client.force_login(self.admin)
        response = self.queue()
        self.assertEqual(list(response.context["flagged_comments"]), [flagged])
        self.assertContains(response, self.moderate_url(flagged))
        self.assertContains(response, "Violets vs Bobcats")
        self.assertEqual(flagged_total(), 1)

    def test_queue_empty_state(self):
        self.client.force_login(self.admin)
        self.assertContains(self.queue(), "No flagged comments")

    def test_player_cannot_moderate(self):
        comment = self.comment(is_flagged=True)
        self.client.force_login(self.player)
        response = self.client.post(self.moderate_url(comment), {"action": "dismiss"})
        self.assertEqual(response.status_code, 403)
        comment.refresh_from_db()
        self.assertTrue(comment.is_flagged)

    def test_dismiss_clears_the_report(self):
        comment = self.comment(is_flagged=True)
        self.client.force_login(self.admin)
        response = self.client.post(self.moderate_url(comment), {"action": "dismiss"})
        self.assertRedirects(response, reverse("chat:moderation_queue"))
        comment.refresh_from_db()
        self.assertFalse(comment.is_flagged)

    def test_delete_removes_the_comment(self):
        comment = self.comment(is_flagged=True)
        self.client.force_login(self.admin)
        self.client.post(self.moderate_url(comment), {"action": "delete"})
        self.assertFalse(MatchComment.objects.exists())
        self.assertTrue(AuditLog.objects.filter(object_type="MatchComment").exists())

    def test_unknown_action_changes_nothing(self):
        comment = self.comment(is_flagged=True)
        self.client.force_login(self.admin)
        self.client.post(self.moderate_url(comment), {"action": "ban"})
        comment.refresh_from_db()
        self.assertTrue(comment.is_flagged)
