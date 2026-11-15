from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from core.templatetags.ui import player_name
from teams.models import EventType, Roster

from .models import Match, MatchAppearance, MatchPeriodScore, PlayerStat
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
