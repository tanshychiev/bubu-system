from django.contrib import admin
from .models import Delivery


@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "customer_name",
        "phone",
        "total_price",
        "payment_type",
        "expected_collect",
        "actual_received",
        "lack_amount",
        "delivery_fee",
        "delivery_fee_paid",
        "status",
        "delivery_date",
        "created_at",
    )

    list_filter = (
        "status",
        "payment_type",
        "delivery_fee_paid",
        "delivery_date",
    )

    search_fields = (
        "customer_name",
        "phone",
        "location",
        "delivery_note",
    )

    readonly_fields = ("created_at", "updated_at")
    ordering = ("-created_at",)