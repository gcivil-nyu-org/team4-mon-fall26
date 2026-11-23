from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from facilities.models import Facility
from matches.models import Match

from .models import Division, Roster, Season, Sport, Team
from .season_rules import SeasonState
from .tests import make_user


class TeamDirectoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.soccer = Sport.objects.create(name="Soccer")
        cls.hoops = Sport.objects.create(name="Basketball")
        cls.fall = Season.objects.create(
            name="Fall",
            start_date="2026-09-01",
            state=SeasonState.OPEN,
        )
        cls.spring = Season.objects.create(
            name="Spring", start_date="2027-01-01", state=SeasonState.DRAFT
        )
        cls.gold = Division.objects.create(season=cls.fall, name="A")
        captain = make_user("cap")
        cls.violets = Team.objects.create(
            name="Violets",
            sport=cls.soccer,
            season=cls.fall,
            division=cls.gold,
            captain=captain,
        )
        Roster.objects.create(
            team=cls.violets, player=captain, role=Roster.Role.CAPTAIN
        )
        cls.bobcats = Team.objects.create(
            name="Bobcats", sport=cls.soccer, season=cls.fall, captain=captain
        )
        cls.hoopers = Team.objects.create(
            name="Hoopers", sport=cls.hoops, season=cls.fall, captain=captain
        )
        cls.ghosts = Team.objects.create(
            name="Ghosts", sport=cls.soccer, season=cls.spring, captain=captain
        )
        cls.loners = Team.objects.create(
            name="Loners", sport=cls.soccer, captain=captain
        )
        cls.viewer = make_user("viewer")
        Roster.objects.create(team=cls.violets, player=cls.viewer)
        cls.url = reverse("teams:directory")

    def setUp(self):
        self.client.force_login(self.viewer)

    def names(self, response):
        return [row["team"].name for row in response.context["rows"]]

    def test_lists_visible_teams_and_hides_draft(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        for name in ("Violets", "Bobcats", "Hoopers", "Loners"):
            self.assertContains(response, name)
        self.assertNotContains(response, "Ghosts")

    def test_admin_sees_draft_teams(self):
        admin = make_user("boss")
        admin.is_superuser = True
        admin.save()
        self.client.force_login(admin)
        self.assertContains(self.client.get(self.url), "Ghosts")

    def test_filters(self):
        for params, expected in [
            ({"sport": self.soccer.pk}, {"Violets", "Bobcats", "Loners"}),
            ({"season": self.fall.pk, "division": self.gold.pk}, {"Violets"}),
            ({"q": "  vIoL "}, {"Violets"}),
        ]:
            with self.subTest(params=params):
                self.assertEqual(
                    set(self.names(self.client.get(self.url, params))), expected
                )

    def test_bad_filter_values_are_ignored(self):
        foreign = Division.objects.create(season=self.spring, name="B")
        cases = [
            ({"sport": "x"}, {"Violets", "Bobcats", "Hoopers", "Loners"}),
            ({"season": "999"}, {"Violets", "Bobcats", "Hoopers", "Loners"}),
            (
                {"season": self.fall.pk, "division": foreign.pk},
                {"Violets", "Bobcats", "Hoopers"},
            ),
        ]
        for params, expected in cases:
            with self.subTest(params=params):
                response = self.client.get(self.url, params)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(set(self.names(response)), expected)

    def test_division_select_is_disabled_until_a_season_is_chosen(self):
        # #275: the filter always shows, so people can see it exists.
        response = self.client.get(self.url)
        self.assertContains(response, 'name="division" aria-describedby')
        self.assertContains(response, " disabled>")
        self.assertContains(response, "Pick a season and filter to choose a division.")
        response = self.client.get(self.url, {"season": self.fall.pk})
        self.assertContains(response, 'name="division"')
        self.assertNotContains(response, " disabled>")
        self.assertContains(response, f'value="{self.gold.pk}"')

    def test_sport_narrows_the_season_list(self):
        # #275: a season of another sport can't hold this sport's teams.
        hoops_season = Season.objects.create(
            name="Hoops Fall",
            start_date="2026-09-02",
            state=SeasonState.OPEN,
            sport=self.hoops,
        )
        response = self.client.get(self.url, {"sport": self.soccer.pk})
        seasons = list(response.context["seasons"])
        self.assertIn(self.fall, seasons)
        self.assertNotIn(hoops_season, seasons)
        response = self.client.get(self.url, {"sport": self.hoops.pk})
        self.assertIn(hoops_season, list(response.context["seasons"]))

    def test_season_of_another_sport_is_dropped(self):
        hoops_season = Season.objects.create(
            name="Hoops Fall",
            start_date="2026-09-02",
            state=SeasonState.OPEN,
            sport=self.hoops,
        )
        response = self.client.get(
            self.url, {"sport": self.soccer.pk, "season": hoops_season.pk}
        )
        self.assertIsNone(response.context["selected"]["season"])
        self.assertEqual(set(self.names(response)), {"Violets", "Bobcats", "Loners"})

    def test_nul_in_search_is_dropped(self):
        # #295: PostgreSQL rejects NUL in a text parameter.
        response = self.client.get(self.url, {"q": "Vio\x00lets"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected"]["q"], "Violets")
        self.assertEqual(self.names(response), ["Violets"])
        response = self.client.get(self.url, {"q": "\x00"})
        self.assertEqual(response.context["selected"]["q"], "")

    def test_pagination_keeps_filters(self):
        captain = make_user("other-cap")
        for index in range(25):
            Team.objects.create(
                name=f"Side {index:02d}",
                sport=self.soccer,
                season=self.fall,
                captain=captain,
            )
        params = {"sport": self.soccer.pk}
        page1 = self.client.get(self.url, {**params, "page": 1})
        self.assertEqual(len(page1.context["page_obj"]), 20)
        page2 = self.client.get(self.url, {**params, "page": 2})
        self.assertEqual(len(page2.context["page_obj"]), 8)
        self.assertContains(page2, f"?sport={self.soccer.pk}&page=1")
        last = self.client.get(self.url, {**params, "page": 999})
        self.assertEqual(last.status_code, 200)
        self.assertEqual(
            list(last.context["page_obj"]), list(page2.context["page_obj"])
        )

    def test_row_shows_record_and_position_and_marks_mine(self):
        field = Facility.objects.create(name="Pier 40", source=Facility.Source.NYU)
        now = timezone.now()
        Match.objects.create(
            season=self.fall,
            home_team=self.violets,
            away_team=self.bobcats,
            facility=field,
            starts_at=now - timezone.timedelta(days=2),
            ends_at=now - timezone.timedelta(days=2, hours=-2),
            home_score=2,
            away_score=0,
        )
        response = self.client.get(self.url)
        self.assertContains(response, "1st of 3")
        self.assertContains(response, "pn-row-me")
        self.assertContains(response, "–")

    def test_query_count_is_fixed(self):
        from matches.test_stats import count_queries

        small = count_queries(lambda: self.client.get(self.url))
        captain = make_user("other-cap")
        extra_seasons = [
            Season.objects.create(
                name=name, start_date="2027-02-01", state=SeasonState.OPEN
            )
            for name in ("Extra one", "Extra two")
        ]
        for index in range(22):
            Team.objects.create(
                name=f"Extra {index:02d}",
                sport=self.hoops,
                season=extra_seasons[index % 2],
                captain=captain,
            )
        self.assertEqual(count_queries(lambda: self.client.get(self.url)), small)

    def test_my_teams_and_directory_link_each_other(self):
        response = self.client.get(reverse("teams:list"))
        self.assertContains(response, reverse("teams:directory"))
        response = self.client.get(self.url)
        self.assertContains(response, reverse("teams:list"))

    def test_empty_state(self):
        response = self.client.get(self.url, {"q": "zzz"})
        self.assertContains(response, "No teams match these filters")
        self.assertContains(response, reverse("teams:directory"))
