"""The Player leaders page (#311). The ranking lives in leaderboards.py."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .leaderboards import (
    LEADERBOARD_LIMIT,
    MIN_GAMES_FOR_PER_GAME,
    default_sport,
    leaderboard_seasons,
    leaderboard_sports,
    player_leaderboards,
    season_for,
    sport_of_season,
)

ALL_SEASONS = "all"


@login_required
def player_leaders(request):
    """Players ranked by each stat of one sport, for one season or all of them.

    GET takes `sport` and `season` (a season id or "all"). A value that isn't
    on offer falls back to the default: the viewer's sport, newest season.
    """
    user = request.user
    sports = list(leaderboard_sports())
    sport_id = request.GET.get("sport", "")
    season_id = request.GET.get("season", "")
    if not sport_id.isdecimal():
        # A link from a season's standings passes only the season.
        sport_id = str(sport_of_season(season_id) or "")
    sport = next((s for s in sports if str(s.pk) == sport_id), None)
    sport = sport or default_sport(user, sports)

    seasons, season, boards = [], None, []
    if sport is not None:
        seasons = list(leaderboard_seasons(user, sport))
        if season_id != ALL_SEASONS:
            season = season_for(seasons, season_id) or (seasons[0] if seasons else None)
        boards = player_leaderboards(user, sport, season)
    return render(
        request,
        "matches/player_leaders.html",
        {
            "sports": sports,
            "sport": sport,
            "seasons": seasons,
            "season": season,
            "all_seasons": ALL_SEASONS,
            "boards": boards,
            "limit": LEADERBOARD_LIMIT,
            "min_games": MIN_GAMES_FOR_PER_GAME,
            "nav_section": "schedule",
        },
    )
