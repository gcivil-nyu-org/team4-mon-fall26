from django.contrib import admin

from .models import PendingAccount


@admin.register(PendingAccount)
class PendingAccountAdmin(admin.ModelAdmin):
    list_display = ["user", "invited_by", "created_at"]
    search_fields = ["user__email"]
    raw_id_fields = ["user", "invited_by"]
