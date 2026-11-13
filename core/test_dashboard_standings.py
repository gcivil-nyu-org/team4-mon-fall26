import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.roles import LEAGUE_ADMIN_ROLE, assign_role
from facilities.models import Facility
from matches.models import Match
from matches.standings import dashboard_standings
from teams.models import Roster, Season, Sport, Team
from teams.season_rules import SeasonState
from teams.semesters import current_semester
from teams.tests import make_user

TODAY = datetime.date(2026, 11, 13)
TERM = "2026-fall"


class DashboardStandingsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.player = make_user("alex")
        cls.captain = make_user("cap")
        cls.soccer = Sport.objects.create(name="Soccer")
        cls.hoops = Sport.objects.create(name="Basketball")
        cls.volley = Sport.objects.create(name="Volleyball")
        cls.seasons = {
            sport: cls.make_season(sport)
            for sport in (cls.soccer, cls.hoops, cls.volley)
        }

    @classmethod
    def make_season(cls, sport, term=TERM, state=SeasonState.OPEN):
        return Season.objects.create(
            name=f"Fall 2026 {sport.name}",
            start_date=datetime.date(2026, 9, 1),
            sport=sport,
            term=term,
            state=state,
        )

    def make_team(self, name, sport, season=None):
        return Team.objects.create(
            name=name,
            sport=sport,
            season=season or self.seasons[sport],
            captain=self.captain,
        )

    def join(self, team, joined_at=None):
        entry = Roster.objects.create(team=team, player=self.player)
        if joined_at:
            Roster.objects.filter(pk=entry.pk).update(joined_at=joined_at)

    def tabs(self, user=None):
        return dashboard_standings(user or self.player, TODAY)[1]

    def sport_names(self, user=None):
        return [tab["sport"].name for tab in self.tabs(user)]

    def test_label_is_current_semester(self):
        self.assertEqual(dashboard_standings(self.player, TODAY)[0], "Fall 2026")

    def test_player_with_no_teams_sees_all_sports_alphabetically(self):
        self.assertEqual(self.sport_names(), ["Basketball", "Soccer", "Volleyball"])
        self.assertFalse(any(tab["is_mine"] for tab in self.tabs()))

    def test_my_sports_first_by_latest_join_then_alphabetical(self):
        now = timezone.now()
        self.join(self.make_team("Violets", self.soccer), now)
        # A team in another season still makes the sport "mine".
        old = Season.objects.create(
            name="Old volleyball", start_date=datetime.date(2025, 9, 1)
        )
        self.join(
            self.make_team("Spikers", self.volley, old),
            now + datetime.timedelta(days=1),
        )
        tabs = self.tabs()
        self.assertEqual(
            [tab["sport"].name for tab in tabs], ["Volleyball", "Soccer", "Basketball"]
        )
        self.assertEqual([tab["is_mine"] for tab in tabs], [True, True, False])
        self.assertEqual(tabs[0]["season"], self.seasons[self.volley])

    def test_rows_mark_my_team(self):
        mine = self.make_team("Violets", self.soccer)
        theirs = self.make_team("Bobcats", self.soccer)
        self.join(mine)
        Match.objects.create(
            season=self.seasons[self.soccer],
            home_team=mine,
            away_team=theirs,
            facility=Facility.objects.create(
                name="Pier 40", source=Facility.Source.NYU
            ),
            starts_at=timezone.now(),
            ends_at=timezone.now() + datetime.timedelta(hours=1),
            home_score=2,
            away_score=1,
        )
        soccer = self.tabs()[0]
        self.assertEqual(soccer["sport"], self.soccer)
        self.assertEqual(
            [(row["team"], row["is_me"], row["points"]) for row in soccer["rows"]],
            [(mine, True, 3), (theirs, False, 0)],
        )

    def test_sport_with_no_teams_has_empty_rows(self):
        self.make_team("Violets", self.soccer)
        rows = {tab["sport"].name: tab["rows"] for tab in self.tabs()}
        self.assertEqual(len(rows["Soccer"]), 1)
        self.assertEqual(rows["Basketball"], [])

    def test_draft_seasons_hidden_from_players(self):
        tennis = Sport.objects.create(name="Tennis")
        self.make_season(tennis, state=SeasonState.DRAFT)
        self.assertNotIn("Tennis", self.sport_names())
        admin = make_user("admin")
        assign_role(admin, LEAGUE_ADMIN_ROLE)
        self.assertIn("Tennis", self.sport_names(admin))

    def test_custom_seasons_not_included(self):
        tennis = Sport.objects.create(name="Tennis")
        self.make_season(tennis, term="")
        Season.objects.create(
            name="Any sport", start_date=datetime.date(2026, 9, 1), term=""
        )
        self.assertEqual(self.sport_names(), ["Basketball", "Soccer", "Volleyball"])

    def test_only_current_term_included(self):
        self.make_season(self.soccer, term="2027-spring")
        self.make_season(self.soccer, term="2026-spring")
        tabs = self.tabs()
        self.assertEqual(len(tabs), 3)
        self.assertEqual({tab["season"].term for tab in tabs}, {TERM})

    def test_dashboard_renders_standings(self):
        term = current_semester(timezone.localdate()).term
        Season.objects.filter(sport=self.hoops).update(term=term)
        self.client.force_login(self.player)
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        names = [tab["sport"].name for tab in response.context["standings_tabs"]]
        self.assertIn("Basketball", names)
        self.assertContains(response, "Basketball")
