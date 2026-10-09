
from django.contrib import admin

from .models import SystemLog


@admin.register(SystemLog)
class SystemLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "level", "category", "event", "actor_label", "status_code")
    list_filter = ("level", "category", "created_at")
    search_fields = ("event", "message", "source", "actor_label", "path", "ip_address")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = (
        "created_at", "level", "category", "event", "message", "source", "actor",
        "actor_label", "ip_address", "request_method", "path", "status_code", "metadata",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
