from django.contrib import admin

from .models import PlayerProfile


@admin.register(PlayerProfile)
class PlayerProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "net_id", "n_number")
    search_fields = ("user__email", "net_id", "n_number")
