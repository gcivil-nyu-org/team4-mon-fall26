"""Automatic season state changes by date (#215). Rules: docs/E2_CONTRACT.md."""

import datetime
from io import StringIO
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.roles import LEAGUE_ADMIN_ROLE, assign_role
from audit.models import AuditLog

from .forms import SeasonForm
from .management.commands.seed_semester_seasons import REGISTRATION_WEEKS
from .models import Season, Sport
from .season_rules import SeasonState, automatic_states

START = datetime.date(2026, 9, 1)
REG = datetime.date(2026, 9, 22)
END = datetime.date(2026, 12, 15)
DRAFT, OPEN, ACTIVE, CLOSED = (
    SeasonState.DRAFT,
    SeasonState.OPEN,
    SeasonState.ACTIVE,
    SeasonState.CLOSED,
)


def day(value):
    return datetime.date.fromisoformat(value)


def make_season(state=OPEN, name="Fall 2026", reg=REG, end=END, auto=True):
    return Season.objects.create(
        name=name,
        start_date=START,
        end_date=end,
        registration_closes_on=reg,
        auto_state=auto,
        state=state,
    )


def advance(today, *args):
    out = StringIO()
    call_command("advance_season_states", "--today", today, *args, stdout=out)
    return out.getvalue().rstrip().splitlines()


def state_of(season):
    season.refresh_from_db()
    return season.state


class AutomaticStatesRuleTests(SimpleTestCase):
    def steps(self, state, today, auto=True, reg=REG, end=END):
        return automatic_states(state, auto, reg, end, day(today))

    def test_open_stays_open_through_the_registration_close_date(self):
        self.assertEqual(self.steps(OPEN, "2026-09-21"), [])
        self.assertEqual(self.steps(OPEN, "2026-09-22"), [])

    def test_open_becomes_active_the_day_after_registration_closes(self):
        self.assertEqual(self.steps(OPEN, "2026-09-23"), [ACTIVE])

    def test_start_date_does_not_make_an_open_season_active(self):
        # The rule takes no start date: only the registration date counts.
        self.assertEqual(self.steps(OPEN, "2026-11-13", reg=None), [])
        self.assertEqual(self.steps(OPEN, "2027-01-01", reg=None), [])

    def test_active_stays_active_through_the_end_date(self):
        self.assertEqual(self.steps(ACTIVE, "2026-12-15"), [])

    def test_active_becomes_closed_the_day_after_the_end_date(self):
        self.assertEqual(self.steps(ACTIVE, "2026-12-16"), [CLOSED])

    def test_active_with_no_end_date_never_closes(self):
        self.assertEqual(self.steps(ACTIVE, "2030-01-01", end=None), [])

    def test_open_past_both_dates_goes_active_then_closed(self):
        self.assertEqual(self.steps(OPEN, "2026-12-16"), [ACTIVE, CLOSED])

    def test_open_past_registration_with_no_end_date_only_goes_active(self):
        self.assertEqual(self.steps(OPEN, "2030-01-01", end=None), [ACTIVE])

    def test_draft_and_closed_never_change(self):
        self.assertEqual(self.steps(DRAFT, "2030-01-01"), [])
        self.assertEqual(self.steps(CLOSED, "2030-01-01"), [])

    def test_opt_out_never_changes(self):
        for state in SeasonState.values:
            self.assertEqual(self.steps(state, "2030-01-01", auto=False), [])


class AdvanceSeasonStatesCommandTests(TestCase):
    def test_open_season_becomes_active_after_registration_closes(self):
        season = make_season(OPEN)
        self.assertEqual(
            advance("2026-09-22"), ["Season states: 0 changed, 1 unchanged."]
        )
        self.assertEqual(state_of(season), OPEN)
        self.assertEqual(
            advance("2026-09-23"),
            ["  Fall 2026: Open → Active", "Season states: 1 changed, 0 unchanged."],
        )
        self.assertEqual(state_of(season), ACTIVE)

    def test_active_season_closes_after_its_end_date(self):
        season = make_season(ACTIVE)
        advance("2026-12-15")
        self.assertEqual(state_of(season), ACTIVE)
        self.assertEqual(
            advance("2026-12-16"),
            ["  Fall 2026: Active → Closed", "Season states: 1 changed, 0 unchanged."],
        )
        self.assertEqual(state_of(season), CLOSED)

    def test_open_season_with_no_registration_date_stays_open(self):
        season = make_season(OPEN, reg=None)
        advance("2027-06-01")
        self.assertEqual(state_of(season), OPEN)

    def test_active_season_with_no_end_date_stays_active(self):
        season = make_season(ACTIVE, end=None)
        advance("2030-01-01")
        self.assertEqual(state_of(season), ACTIVE)

    def test_draft_season_never_changes(self):
        season = make_season(DRAFT)
        self.assertEqual(
            advance("2030-01-01"), ["Season states: 0 changed, 1 unchanged."]
        )
        self.assertEqual(state_of(season), DRAFT)

    def test_closed_season_is_left_alone(self):
        season = make_season(CLOSED)
        advance("2030-01-01")
        self.assertEqual(state_of(season), CLOSED)

    def test_opted_out_seasons_never_change(self):
        opened = make_season(OPEN, name="Open", auto=False)
        active = make_season(ACTIVE, name="Active", auto=False)
        self.assertEqual(
            advance("2030-01-01"), ["Season states: 0 changed, 2 unchanged."]
        )
        self.assertEqual((state_of(opened), state_of(active)), (OPEN, ACTIVE))

    def test_both_dates_past_moves_through_active_to_closed_in_order(self):
        season = make_season(OPEN)
        targets = []
        real_move_to = Season.move_to

        def spy(self, target):
            targets.append(target)
            return real_move_to(self, target)

        with mock.patch.object(Season, "move_to", spy):
            lines = advance("2026-12-16")
        self.assertEqual(targets, [ACTIVE, CLOSED])
        self.assertEqual(lines[0], "  Fall 2026: Open → Active → Closed")
        self.assertEqual(lines[-1], "Season states: 1 changed, 0 unchanged.")
        self.assertEqual(state_of(season), CLOSED)

    def test_one_run_only_takes_the_steps_that_are_due(self):
        season = make_season(OPEN)
        advance("2026-10-01")
        self.assertEqual(state_of(season), ACTIVE)

    def test_second_run_changes_nothing(self):
        make_season(OPEN)
        advance("2026-09-23")
        self.assertEqual(
            advance("2026-09-23"), ["Season states: 0 changed, 1 unchanged."]
        )

    def test_dry_run_lists_changes_and_saves_nothing(self):
        opened = make_season(OPEN, name="A")
        active = make_season(ACTIVE, name="B")
        logs = AuditLog.objects.count()
        self.assertEqual(
            advance("2026-12-16", "--dry-run"),
            [
                "  A: Open → Active → Closed",
                "  B: Active → Closed",
                "Season states (dry run): 2 would change, 0 unchanged.",
            ],
        )
        self.assertEqual((state_of(opened), state_of(active)), (OPEN, ACTIVE))
        self.assertEqual(AuditLog.objects.count(), logs)

    def test_mixed_seasons_are_counted(self):
        make_season(OPEN, name="Moves")
        make_season(DRAFT, name="Draft")
        make_season(OPEN, name="No date", reg=None)
        make_season(OPEN, name="Opted out", auto=False)
        self.assertEqual(
            advance("2026-09-23"),
            ["  Moves: Open → Active", "Season states: 1 changed, 3 unchanged."],
        )

    def test_today_defaults_to_the_local_date(self):
        season = make_season(OPEN)
        with mock.patch(
            "teams.management.commands.advance_season_states.timezone.localdate",
            return_value=day("2026-09-23"),
        ):
            call_command("advance_season_states", stdout=StringIO())
        self.assertEqual(state_of(season), ACTIVE)

    def test_bad_today_is_an_error(self):
        with self.assertRaisesMessage(CommandError, "--today must be YYYY-MM-DD"):
            advance("tomorrow")

    def test_each_change_writes_an_audit_row_with_no_actor(self):
        season = make_season(OPEN)
        before = AuditLog.objects.count()
        advance("2026-12-16")
        rows = list(AuditLog.objects.order_by("pk")[before:])
        self.assertEqual(len(rows), 2)  # open → active, then active → closed
        for row in rows:
            self.assertEqual(
                (row.action, row.object_type, row.object_id, row.object_repr),
                (AuditLog.Action.UPDATED, "Season", str(season.pk), "Fall 2026"),
            )
            self.assertIsNone(row.actor)

    def test_unchanged_seasons_write_no_audit_row(self):
        make_season(DRAFT)
        make_season(OPEN, name="No date", reg=None)
        before = AuditLog.objects.count()
        advance("2030-01-01")
        self.assertEqual(AuditLog.objects.count(), before)


class RegistrationDateValidationTests(TestCase):
    def test_registration_after_end_date_is_invalid(self):
        season = Season(
            name="Bad",
            start_date=START,
            end_date=END,
            registration_closes_on=END + datetime.timedelta(days=1),
        )
        with self.assertRaises(ValidationError) as caught:
            season.full_clean()
        self.assertIn("registration_closes_on", caught.exception.message_dict)

    def test_registration_on_end_date_or_with_no_end_date_is_valid(self):
        Season(
            name="A", start_date=START, end_date=END, registration_closes_on=END
        ).full_clean()
        Season(name="B", start_date=START, registration_closes_on=END).full_clean()

    def test_new_seasons_change_state_automatically_by_default(self):
        season = Season.objects.create(name="New", start_date=START)
        self.assertTrue(season.auto_state)
        self.assertIsNone(season.registration_closes_on)


class SeasonFormAutoStateTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="admin1", email="admin1@nyu.edu", password="pass12345!"
        )
        assign_role(user, LEAGUE_ADMIN_ROLE)
        self.client.force_login(user)

    def data(self, **extra):
        return {
            "name": "Fall 2026",
            "start_date": "2026-09-01",
            "end_date": "2026-12-15",
            "max_roster_size": 12,
            **extra,
        }

    def test_form_shows_both_fields(self):
        response = self.client.get(reverse("teams:create_season"))
        self.assertContains(response, 'name="registration_closes_on"')
        self.assertContains(response, 'name="auto_state"')
        self.assertContains(response, "On the next day the season becomes active.")

    def test_create_saves_registration_date_and_opt_out(self):
        self.client.post(
            reverse("teams:create_season"),
            self.data(registration_closes_on="2026-09-22", auto_state="off"),
        )
        season = Season.objects.get()
        self.assertEqual(season.registration_closes_on, REG)
        self.assertFalse(season.auto_state)

    def test_edit_can_turn_automatic_changes_back_on(self):
        season = make_season(auto=False)
        self.client.post(
            reverse("teams:edit_season", args=[season.pk]),
            self.data(auto_state="on"),
        )
        season.refresh_from_db()
        self.assertTrue(season.auto_state)
        self.assertIsNone(season.registration_closes_on)

    def test_post_without_the_setting_keeps_it(self):
        season = make_season(auto=False)
        form = SeasonForm(self.data(), instance=season)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertFalse(form.save().auto_state)
        self.assertTrue(SeasonForm(self.data(name="Other")).save().auto_state)

    def test_edit_form_selects_the_current_setting(self):
        self.assertEqual(SeasonForm(instance=make_season()).initial["auto_state"], "on")
        off = make_season(name="Off", auto=False)
        self.assertEqual(SeasonForm(instance=off).initial["auto_state"], "off")

    def test_registration_after_end_date_is_rejected(self):
        response = self.client.post(
            reverse("teams:create_season"),
            self.data(registration_closes_on="2026-12-16"),
        )
        self.assertContains(
            response, "Registration can&#x27;t close after the end date."
        )
        self.assertFalse(Season.objects.exists())

    def hints(self, **kwargs):
        make_season(**kwargs)
        return self.client.get(reverse("teams:manage_seasons"))

    def test_list_shows_both_hints_for_an_open_season(self):
        self.assertContains(
            self.hints(state=OPEN),
            "Registration closes Sep 22, 2026 · "
            "Closes automatically after Dec 15, 2026",
        )

    def test_list_shows_only_the_close_hint_for_an_active_season(self):
        response = self.hints(state=ACTIVE)
        self.assertNotContains(response, "Registration closes")
        self.assertContains(response, "Closes automatically after Dec 15, 2026")

    def test_list_shows_no_hints_without_dates(self):
        response = self.hints(state=OPEN, reg=None)
        self.assertNotContains(response, "Registration closes")
        self.assertNotContains(response, "Closes automatically")

    def test_list_shows_no_hints_when_opted_out_or_closed(self):
        make_season(state=CLOSED, name="Done")
        response = self.hints(state=ACTIVE, auto=False)
        self.assertNotContains(response, "Registration closes")
        self.assertNotContains(response, "Closes automatically")


class SeedRegistrationDateTests(TestCase):
    def setUp(self):
        self.soccer = Sport.objects.create(name="Soccer")

    def seed(self, today):
        call_command("seed_semester_seasons", "--today", today, stdout=StringIO())

    def season(self, term):
        return Season.objects.get(sport=self.soccer, term=term)

    def test_new_seasons_get_a_date_three_weeks_after_the_semester_start(self):
        self.assertEqual(REGISTRATION_WEEKS, 3)
        self.seed("2026-09-05")
        self.assertEqual(self.season("2026-fall").registration_closes_on, REG)
        self.assertEqual(
            self.season("2027-spring").registration_closes_on, day("2027-02-10")
        )
        self.assertTrue(self.season("2026-fall").auto_state)

    def test_season_created_on_the_close_date_still_gets_it(self):
        self.seed("2026-09-22")
        self.assertEqual(self.season("2026-fall").registration_closes_on, REG)

    def test_season_created_after_the_close_date_gets_no_date(self):
        self.seed("2026-11-13")
        self.assertIsNone(self.season("2026-fall").registration_closes_on)
        # The next semester's draft still gets its date.
        self.assertEqual(
            self.season("2027-spring").registration_closes_on, day("2027-02-10")
        )

    def test_fresh_mid_semester_deploy_keeps_registration_open(self):
        self.seed("2026-11-13")
        advance("2026-11-13")
        self.assertEqual(self.season("2026-fall").state, OPEN)
        self.assertEqual(self.season("2027-spring").state, DRAFT)

    def test_existing_seasons_are_not_given_a_date(self):
        existing = Season.objects.create(
            name="Fall 2026 Soccer",
            sport=self.soccer,
            term="2026-fall",
            start_date=START,
            end_date=END,
            state=OPEN,
        )
        self.seed("2026-09-05")
        existing.refresh_from_db()
        self.assertIsNone(existing.registration_closes_on)
        advance("2026-11-13")
        self.assertEqual(state_of(existing), OPEN)

    def test_seeded_season_becomes_active_then_closed_on_later_runs(self):
        self.seed("2026-09-05")
        advance("2026-09-23")
        self.assertEqual(self.season("2026-fall").state, ACTIVE)
        advance("2026-12-16")
        self.assertEqual(self.season("2026-fall").state, CLOSED)
        self.assertEqual(self.season("2027-spring").state, DRAFT)


class DeployConfigTests(SimpleTestCase):
    def test_command_runs_after_the_seeds_and_before_permissions(self):
        config = Path(settings.BASE_DIR, ".ebextensions", "django.config").read_text()
        keys = [
            line.strip().rstrip(":")
            for line in config.split("container_commands:")[1].splitlines()
            if line.startswith("  ")
            and not line.startswith("   ")
            and not line.strip().startswith("#")
        ]
        self.assertEqual(keys, sorted(keys))  # Elastic Beanstalk runs them sorted
        self.assertEqual(keys[-2:], ["03g_advance_season_states", "04_fix_permissions"])
        self.assertIn("manage.py advance_season_states || true", config)
