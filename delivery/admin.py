from django.contrib import admin
from .models import DeliveryOrder, DeliveryStatusLog


@admin.register(DeliveryOrder)
class DeliveryOrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "customer_name",
        "phone",
        "delivery_fee",
        "status",
        "created_at",
        "delivered_at",
    )
    list_filter = ("status", "created_at", "delivered_at")
    search_fields = ("customer_name", "phone", "address", "note")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)


@admin.register(DeliveryStatusLog)
class DeliveryStatusLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "delivery",
        "old_status",
        "new_status",
        "changed_by",
        "created_at",
    )
    list_filter = ("old_status", "new_status", "created_at")
    search_fields = ("delivery__customer_name", "delivery__phone", "note")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)