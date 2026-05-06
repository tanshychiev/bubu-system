from django.contrib import admin

from .models import StaffProfile


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "branch",
        "created_at",
        "updated_at",
    )

    list_filter = (
        "branch",
    )

    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
        "user__email",
        "branch__name",
    )