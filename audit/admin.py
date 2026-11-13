from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "timestamp",
        "actor",
        "action",
        "object_type",
        "object_id",
        "object_repr",
    )
    list_filter = ("action", "object_type")
    search_fields = ("object_repr", "object_id", "actor__username")
    readonly_fields = (
        "actor",
        "action",
        "timestamp",
        "object_type",
        "object_id",
        "object_repr",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
