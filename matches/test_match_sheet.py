import datetime

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from core.templatetags.ui import player_name
from teams.models import EventType, Roster, Season
from teams.season_rules import SeasonState

from .models import Match, MatchAppearance, MatchPeriodScore, PlayerStat
from .sheet_forms import MatchSheet
from .stats import period_rows, save_match_sheet, team_sheets
from .tests import MatchFixtures, ScorekeeperFixtures, make_user


def named_user(username, first="", last=""):
    user = make_user(username)
    user.first_name = first
    user.last_name = last
    user.save()
    return user


class SheetFixtures(ScorekeeperFixtures):
    def setUp(self):
        self.match = self.build()
        self.match.save()
        self.match = Match.objects.select_related(
            "season", "home_team__sport", "away_team__sport"
        ).get(pk=self.match.pk)
        self.alex = named_user("alex", "Alex", "Lee")
        self.sam = named_user("sam", "Sam", "Kim")
        self.jo = named_user("jo", "Jo", "Park")
        Roster.objects.create(team=self.home, player=self.alex)
        Roster.objects.create(team=self.home, player=self.sam)
        Roster.objects.create(team=self.away, player=self.jo)
        self.goal = EventType.objects.create(sport=self.soccer, name="Goal")
        self.assist = EventType.objects.create(sport=self.soccer, name="Assist")

    def key(self, team, player, event_type=None):
        return (team.pk, player.pk, (event_type or self.goal).pk)

    def pair(self, team, player):
        return (team.pk, player.pk)

    def everyone(self):
        return {
            self.pair(self.home, self.alex),
            self.pair(self.home, self.sam),
            self.pair(self.away, self.jo),
        }

    def save(self, **overrides):
        values = dict(
            periods=[],
            final=(1, 0),
            stats={},
            played=set(),
            players=self.everyone(),
        )
        values.update(overrides)
        save_match_sheet(self.match, **values)
        self.match.refresh_from_db()

    def stored_stat(self, team, player, event_type=None, value=2):
        return PlayerStat.objects.create(
            match=self.match,
            team=team,
            player=player,
            event_type=event_type or self.goal,
            value=value,
        )


class SaveMatchSheetTests(SheetFixtures):
    def test_periods_set_the_final_score(self):
        self.save(periods=[(1, 10, 8), (2, 5, 7), (5, 3, 0)], final=(99, 99))
        self.assertEqual((self.match.home_score, self.match.away_score), (18, 15))
        self.assertEqual(self.match.period_scores.count(), 3)
        self.assertEqual(
            period_rows(self.match), [("Q1", 10, 8), ("Q2", 5, 7), ("OT1", 3, 0)]
        )

    def test_final_alone_clears_periods(self):
        self.save(periods=[(1, 1, 1)])
        self.save(periods=[], final=(2, 1))
        self.assertEqual(self.match.period_scores.count(), 0)
        self.assertEqual((self.match.home_score, self.match.away_score), (2, 1))

    def test_zero_stat_deletes_row(self):
        self.stored_stat(self.home, self.alex)
        self.save(stats={self.key(self.home, self.alex): 0})
        self.assertFalse(PlayerStat.objects.exists())

    def test_stat_changes_value(self):
        self.stored_stat(self.home, self.alex)
        self.save(stats={self.key(self.home, self.alex): 5})
        self.assertEqual(PlayerStat.objects.get().value, 5)

    def test_stat_implies_appearance(self):
        self.save(stats={self.key(self.home, self.alex): 1}, played=set())
        self.assertTrue(
            MatchAppearance.objects.filter(
                match=self.match, player=self.alex, team=self.home
            ).exists()
        )

    def test_played_creates_appearance(self):
        self.save(played={self.pair(self.away, self.jo)})
        self.assertEqual(MatchAppearance.objects.get().player, self.jo)

    def test_unchecked_played_deletes_appearance(self):
        self.save(played={self.pair(self.home, self.sam)})
        self.save(played=set())
        self.assertFalse(MatchAppearance.objects.exists())

    def test_rows_outside_players_untouched(self):
        leaver = named_user("leaver", "Lee", "Ver")
        Roster.objects.create(team=self.home, player=leaver)
        self.stored_stat(self.home, leaver)
        MatchAppearance.objects.create(match=self.match, team=self.home, player=leaver)
        Roster.objects.filter(player=leaver).delete()
        self.save()
        self.assertTrue(PlayerStat.objects.filter(player=leaver).exists())
        self.assertTrue(MatchAppearance.objects.filter(player=leaver).exists())

    def test_one_team_per_player(self):
        with self.assertRaises(ValidationError) as caught:
            self.save(
                periods=[(1, 1, 0)],
                played={self.pair(self.home, self.jo), self.pair(self.away, self.jo)},
                players=self.everyone() | {self.pair(self.home, self.jo)},
            )
        self.assertEqual(
            caught.exception.messages, ["Jo Park can only play for one team."]
        )
        self.assertFalse(MatchAppearance.objects.exists())
        self.assertFalse(MatchPeriodScore.objects.exists())
        self.assertIsNone(self.match.home_score)

    def test_stored_leaver_appearance_counts_for_one_team(self):
        # Jo played for home, left, and joined away. Away can't add them again.
        MatchAppearance.objects.create(match=self.match, team=self.away, player=self.jo)
        players = {self.pair(self.home, self.alex), self.pair(self.home, self.jo)}
        with self.assertRaises(ValidationError):
            self.save(played={self.pair(self.home, self.jo)}, players=players)

    def test_error_rolls_back(self):
        self.save(periods=[(1, 1, 0)])
        stranger = make_user("stranger")
        with self.assertRaises(ValidationError):
            self.save(
                periods=[(1, 5, 5)],
                stats={self.key(self.home, stranger): 3},
                players=self.everyone() | {self.pair(self.home, stranger)},
            )
        self.match.refresh_from_db()
        self.assertEqual((self.match.home_score, self.match.away_score), (1, 0))
        self.assertEqual(period_rows(self.match), [("Q1", 1, 0)])
        self.assertFalse(PlayerStat.objects.exists())

    def test_match_closed_since_it_was_read(self):
        # Another request closes the season or cancels the match before the save.
        seasons = Season.objects.filter(pk=self.season.pk)
        matches = Match.objects.filter(pk=self.match.pk)
        for case, close, reopen in (
            (
                "closed season",
                lambda: seasons.update(state=SeasonState.CLOSED),
                lambda: seasons.update(state=SeasonState.OPEN),
            ),
            (
                "cancelled match",
                lambda: matches.update(status=Match.Status.CANCELLED),
                lambda: matches.update(status=Match.Status.SCHEDULED),
            ),
        ):
            with self.subTest(case=case):
                close()
                with self.assertRaises(ValidationError) as caught:
                    self.save(
                        periods=[(1, 1, 0)],
                        stats={self.key(self.home, self.alex): 1},
                    )
                self.assertEqual(
                    caught.exception.messages, ["This match can no longer be scored."]
                )
                self.assertFalse(MatchPeriodScore.objects.exists())
                self.assertFalse(PlayerStat.objects.exists())
                self.match.refresh_from_db()
                self.assertIsNone(self.match.home_score)
                reopen()


class TeamSheetsTests(SheetFixtures):
    def test_team_sheets_rows(self):
        leaver = named_user("bea", "Bea", "Zed")
        Roster.objects.create(team=self.home, player=leaver)
        self.stored_stat(self.home, leaver)
        Roster.objects.filter(player=leaver).delete()
        MatchAppearance.objects.create(
            match=self.match, team=self.home, player=self.alex
        )
        home, away = team_sheets(self.match)
        self.assertEqual(home.team, self.home)
        self.assertEqual(
            [(row.player, row.on_roster, row.played) for row in home.rows],
            [(self.alex, True, True), (self.sam, True, False), (leaver, False, False)],
        )
        self.assertEqual(home.rows[2].stats, {self.goal.pk: 2})
        self.assertEqual([row.player for row in away.rows], [self.jo])

    def test_team_sheets_query_count_is_fixed(self):
        match = Match.objects.select_related("home_team", "away_team").get(
            pk=self.match.pk
        )
        self.stored_stat(self.home, self.alex)
        with self.assertNumQueries(3):
            team_sheets(match)
        for name in ("p1", "p2"):
            user = make_user(name)
            Roster.objects.create(team=self.away, player=user)
            self.stored_stat(self.away, user)
        with self.assertNumQueries(3):
            team_sheets(match)


class PlayerNameTests(MatchFixtures):
    def test_player_name_fallback(self):
        user = get_user_model()(username="x", email="x@nyu.edu")
        self.assertEqual(player_name(user), "PlayNYU player")
        user.first_name = "Alex"
        self.assertEqual(player_name(user), "Alex")
        self.assertEqual(player_name(None), "PlayNYU player")


class MatchSheetFormTests(SheetFixtures):
    def sheet(self, data=None, match=None):
        return MatchSheet(match or self.match, data)

    def periods(self, *rows):
        """Post data for periods: rows of (home, away), "" for blank."""
        data = {}
        for index, (home, away) in enumerate(rows):
            data[f"period-{index}-home_points"] = home
            data[f"period-{index}-away_points"] = away
        return data

    def regular(self, home=1, away=0):
        return [(home, away)] * 4

    def errors(self, sheet):
        self.assertFalse(sheet.is_valid())
        return sheet.non_field_errors()

    def test_period_forms_count(self):
        forms = self.sheet().periods.forms
        self.assertEqual(
            [form.label for form in forms], ["Q1", "Q2", "Q3", "Q4", "OT1", "OT2"]
        )
        self.assertEqual([form.is_overtime for form in forms], [False] * 4 + [True] * 2)
        self.match.home_team.sport.period_count = 0
        self.assertEqual(self.sheet().periods.forms, [])

    def test_period_initial_from_stored_rows(self):
        self.save(periods=[(1, 3, 1), (2, 0, 0), (3, 0, 0), (4, 0, 0)])
        forms = self.sheet().periods.forms
        self.assertEqual(forms[0].initial, {"home_points": 3, "away_points": 1})
        self.assertEqual(forms[4].initial, {})

    def test_partial_regular_periods_fail(self):
        sheet = self.sheet(self.periods((1, 0)))
        self.assertIn(
            "Enter every period, or leave them all blank.", self.errors(sheet)
        )

    def test_overtime_needs_both_points(self):
        sheet = self.sheet(self.periods(*self.regular(), (1, "")))
        self.assertIn("Enter both teams' points.", self.errors(sheet))

    def test_ot2_needs_ot1(self):
        sheet = self.sheet(self.periods(*self.regular(), ("", ""), (1, 0)))
        self.assertIn("Enter OT1 before OT2.", self.errors(sheet))

    def test_overtime_needs_regular(self):
        sheet = self.sheet(self.periods(*[("", "")] * 4, (1, 0)))
        self.assertIn("Enter the regular periods before overtime.", self.errors(sheet))

    def test_final_alone_valid(self):
        sheet = self.sheet({"home_score": "2", "away_score": "1"})
        self.assertTrue(sheet.is_valid(), sheet.non_field_errors())
        sheet.save()
        self.match.refresh_from_db()
        self.assertEqual((self.match.home_score, self.match.away_score), (2, 1))

    def test_nothing_entered_fails(self):
        self.assertIn(
            "Enter both scores, or every period.", self.errors(self.sheet({}))
        )

    def test_periods_override_final(self):
        data = self.periods((10, 8), (5, 7), (0, 0), (3, 0))
        data.update(home_score="1", away_score="0")
        sheet = self.sheet(data)
        self.assertTrue(sheet.is_valid(), sheet.non_field_errors())
        sheet.save()
        self.match.refresh_from_db()
        self.assertEqual((self.match.home_score, self.match.away_score), (18, 15))
        self.assertEqual(self.match.period_scores.count(), 4)

    def test_number_limit(self):
        stat = f"stat-{self.home.pk}-{self.alex.pk}-{self.goal.pk}"
        for data in (
            {"home_score": "1", "away_score": "0", stat: "10000"},
            {"home_score": "10000", "away_score": "0"},
            self.periods((10000, 0), (0, 0), (0, 0), (0, 0)),
        ):
            with self.subTest(data=data):
                self.assertFalse(self.sheet(data).is_valid())
        self.assertFalse(PlayerStat.objects.exists())

    def test_saves_stats_and_played(self):
        data = {
            "home_score": "1",
            "away_score": "0",
            f"stat-{self.home.pk}-{self.alex.pk}-{self.goal.pk}": "2",
            f"stat-{self.home.pk}-{self.alex.pk}-{self.assist.pk}": "",
            f"played-{self.away.pk}-{self.jo.pk}": "on",
        }
        sheet = self.sheet(data)
        self.assertTrue(sheet.is_valid(), sheet.non_field_errors())
        sheet.save()
        self.assertEqual(PlayerStat.objects.get().value, 2)
        self.assertEqual(
            set(MatchAppearance.objects.values_list("player_id", flat=True)),
            {self.alex.pk, self.jo.pk},
        )

    def test_unknown_fields_ignored(self):
        stranger = make_user("stranger")
        data = {
            "home_score": "1",
            "away_score": "0",
            f"stat-{self.away.pk}-{stranger.pk}-{self.goal.pk}": "3",
            f"played-{self.away.pk}-{stranger.pk}": "on",
            f"played-{self.hoops_team.pk}-{self.alex.pk}": "on",
            "period-TOTAL_FORMS": "50",
        }
        sheet = self.sheet(data)
        self.assertTrue(sheet.is_valid(), sheet.non_field_errors())
        sheet.save()
        self.assertFalse(PlayerStat.objects.exists())
        self.assertFalse(MatchAppearance.objects.exists())

    def test_grid_fields_and_labels(self):
        (home_sheet, home_rows), _ = self.sheet().stats.grid
        self.assertEqual(home_sheet.team, self.home)
        row, played, stat_fields = home_rows[0]
        self.assertEqual(row.player, self.alex)
        self.assertEqual(played.name, f"played-{self.home.pk}-{self.alex.pk}")
        self.assertEqual(
            [field.field.widget.attrs["aria-label"] for field in stat_fields],
            ["Alex Lee, Assist", "Alex Lee, Goal"],
        )
        self.assertEqual(played.field.widget.attrs["aria-label"], "Alex Lee played")

    def test_leaver_has_no_inputs(self):
        leaver = named_user("bea", "Bea", "Zed")
        Roster.objects.create(team=self.home, player=leaver)
        self.stored_stat(self.home, leaver)
        Roster.objects.filter(player=leaver).delete()
        _, home_rows = self.sheet().stats.grid[0]
        row, played, stat_fields = home_rows[-1]
        self.assertEqual(row.player, leaver)
        self.assertIsNone(played)
        self.assertEqual(stat_fields, [None, None])

    def test_switched_player_cannot_play_twice(self):
        # Roster.save allows one team per season. Older data can still have two.
        Roster.objects.bulk_create([Roster(team=self.home, player=self.jo)])
        data = {
            "home_score": "1",
            "away_score": "0",
            f"played-{self.home.pk}-{self.jo.pk}": "on",
            f"played-{self.away.pk}-{self.jo.pk}": "on",
        }
        self.assertIn(
            "Jo Park can only play for one team.", self.errors(self.sheet(data))
        )
        self.assertFalse(MatchAppearance.objects.exists())

    def test_writer_error_becomes_form_error(self):
        # Another save adds Jo to home between is_valid() and save().
        data = {
            "home_score": "1",
            "away_score": "0",
            f"played-{self.away.pk}-{self.jo.pk}": "on",
        }
        sheet = self.sheet(data)
        self.assertTrue(sheet.is_valid())
        Roster.objects.bulk_create([Roster(team=self.home, player=self.jo)])
        MatchAppearance.objects.create(match=self.match, team=self.home, player=self.jo)
        Roster.objects.filter(team=self.home, player=self.jo).delete()
        self.assertFalse(sheet.save())
        self.assertIn("Jo Park can only play for one team.", sheet.non_field_errors())

    def test_closed_season(self):
        self.season.state = SeasonState.CLOSED
        self.season.save()
        match = Match.objects.select_related("season", "home_team__sport").get(
            pk=self.match.pk
        )
        sheet = self.sheet({"home_score": "1", "away_score": "0"}, match=match)
        self.assertIn(
            "Scores can only be recorded while the season is open or active.",
            self.errors(sheet),
        )


class ScoreViewTests(SheetFixtures):
    def score_url(self, match=None):
        return reverse("matches:score", args=[(match or self.match).pk])

    def submit_url(self, match):
        return reverse("matches:submit_score", args=[match.pk])

    def detail_url(self, match=None):
        return reverse("matches:detail", args=[(match or self.match).pk])

    def sheet_data(self):
        data = {}
        for index, (home, away) in enumerate([(1, 0), (0, 0), (1, 1), (0, 2)]):
            data[f"period-{index}-home_points"] = home
            data[f"period-{index}-away_points"] = away
        data[f"stat-{self.home.pk}-{self.alex.pk}-{self.goal.pk}"] = "2"
        data[f"played-{self.home.pk}-{self.sam.pk}"] = "on"
        return data

    def under_way(self):
        now = timezone.now()
        return self.assign(
            starts_at=now - datetime.timedelta(hours=1),
            ends_at=now + datetime.timedelta(hours=1),
        )

    def test_admin_saves_sheet_and_goes_to_detail(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.score_url(), self.sheet_data())
        self.assertRedirects(response, self.detail_url())
        self.match.refresh_from_db()
        self.assertEqual((self.match.home_score, self.match.away_score), (2, 3))
        self.assertEqual(PlayerStat.objects.get().value, 2)
        self.assertEqual(MatchAppearance.objects.count(), 2)

    def test_invalid_sheet_shows_errors(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.score_url(), {"period-0-home_points": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enter every period, or leave them all blank.")

    def test_keeper_saves_sheet(self):
        match = self.under_way()
        self.client.force_login(self.keeper)
        response = self.client.post(
            self.submit_url(match), {"home_score": "2", "away_score": "1"}
        )
        self.assertRedirects(response, self.detail_url(match))

    def test_other_keeper_403(self):
        match = self.under_way()
        self.client.force_login(self.other_keeper)
        response = self.client.post(self.submit_url(match), self.sheet_data())
        self.assertEqual(response.status_code, 403)
        self.assertFalse(PlayerStat.objects.exists())

    def test_cancelled_and_closed_redirect_as_today(self):
        match = self.under_way()
        manage = reverse("matches:manage") + f"?season={self.season.pk}"
        match.cancel()
        self.client.force_login(self.admin)
        response = self.client.post(self.score_url(match), follow=True)
        self.assertRedirects(response, manage)
        self.assertContains(response, "Cancelled matches can&#x27;t be scored.")
        self.client.force_login(self.keeper)
        response = self.client.post(self.submit_url(match), follow=True)
        self.assertRedirects(response, reverse("matches:mine"))
        self.season.state = SeasonState.CLOSED
        self.season.save()
        self.client.force_login(self.admin)
        response = self.client.get(self.score_url(), follow=True)
        self.assertRedirects(response, manage)
        self.assertContains(response, "isn&#x27;t open or active.")

    def test_form_shows_grid(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.score_url())
        self.assertContains(response, f'name="played-{self.home.pk}-{self.alex.pk}"')
        self.assertContains(response, "OT1")
        self.assertContains(response, 'aria-label="Alex Lee, Goal"')
        self.assertContains(response, "form-control-sm pn-num text-end")
        self.assertContains(response, self.detail_url())

    def test_leaver_shows_as_text(self):
        leaver = named_user("bea", "Bea", "Zed")
        Roster.objects.create(team=self.home, player=leaver)
        self.stored_stat(self.home, leaver, value=7)
        Roster.objects.filter(player=leaver).delete()
        self.client.force_login(self.admin)
        response = self.client.get(self.score_url())
        self.assertContains(response, "Left team")
        self.assertContains(response, "Bea Zed")
        self.assertNotContains(response, f'name="played-{self.home.pk}-{leaver.pk}"')

    def test_no_email_on_form(self):
        nameless = make_user("nameless")
        Roster.objects.create(team=self.away, player=nameless)
        self.client.force_login(self.admin)
        response = self.client.get(self.score_url())
        self.assertContains(response, "PlayNYU player")
        self.assertNotContains(response, nameless.email)

    def test_no_stat_section_without_event_types(self):
        EventType.objects.filter(sport=self.soccer).delete()
        self.client.force_login(self.admin)
        response = self.client.get(self.score_url())
        self.assertNotContains(response, 'name="stat-')
        self.assertContains(response, f'name="played-{self.home.pk}-{self.alex.pk}"')

    def test_no_period_section_without_periods(self):
        self.soccer.period_count = 0
        self.soccer.save()
        self.client.force_login(self.admin)
        response = self.client.get(self.score_url())
        self.assertNotContains(response, 'name="period-0-home_points"')
        self.assertContains(response, 'name="home_score"')
