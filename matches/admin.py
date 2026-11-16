from django.contrib import admin

from .models import (
    Match,
    MatchAppearance,
    MatchComment,
    MatchPeriodScore,
    PlayerStat,
)

admin.site.register(MatchPeriodScore)
admin.site.register(PlayerStat)
admin.site.register(MatchAppearance)


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ("__str__", "season", "facility", "starts_at", "status")
    list_filter = ("status", "season")
    search_fields = ("home_team__name", "away_team__name", "facility__name")


@admin.register(MatchComment)
class MatchCommentAdmin(admin.ModelAdmin):
    list_display = ("__str__", "created_at", "is_flagged")
    list_filter = ("is_flagged",)
