from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Branch,
    Item,
    ItemType,
    ItemVariant,
    StockMovement,
)


class ItemVariantInline(admin.TabularInline):
    model = ItemVariant
    extra = 1


@admin.register(ItemType)
class ItemTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "emoji", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "brand",
        "item_type",
        "unit",
        "total_stock",
        "cost_price",
        "sale_price",
        "is_active",
    )
    list_filter = ("item_type", "unit", "is_active")
    search_fields = ("name", "brand")
    inlines = [ItemVariantInline]


@admin.register(ItemVariant)
class ItemVariantAdmin(admin.ModelAdmin):
    list_display = (
        "item",
        "color",
        "size",
        "label",
        "quantity",
        "cost_price",
        "sale_price",
        "is_active",
    )
    list_filter = ("is_active", "size", "color")
    search_fields = ("item__name", "color", "size", "label")


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = (
        "item",
        "variant",
        "movement_type",
        "quantity",
        "cost_price",
        "created_by",
        "created_at",
    )
    list_filter = ("movement_type", "created_at")
    search_fields = ("item__name", "variant__label", "note")


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "is_active",
        "payment_qr_status",
        "payment_qr_small_preview",
    )
    list_filter = ("is_active",)
    search_fields = ("name",)
    readonly_fields = (
        "payment_qr_preview",
        "payment_qr_updated_at",
        "customer_display_payment_event_id",
        "customer_display_payment_amount",
        "customer_display_payment_at",
    )

    fieldsets = (
        (
            "Branch",
            {
                "fields": (
                    "name",
                    "is_active",
                )
            },
        ),
        (
            "Customer Display Payment QR",
            {
                "fields": (
                    "payment_qr_image",
                    "payment_qr_preview",
                    "payment_qr_label",
                    "payment_qr_updated_at",
                ),
                "description": (
                    "You can also change this more easily from the normal "
                    "BUBU menu: Customers → Payment QR."
                ),
            },
        ),
        (
            "Latest Customer Display Payment",
            {
                "fields": (
                    "customer_display_payment_event_id",
                    "customer_display_payment_amount",
                    "customer_display_payment_at",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Attendance GPS",
            {
                "fields": (
                    "latitude",
                    "longitude",
                    "allowed_radius_meters",
                )
            },
        ),
    )

    @admin.display(description="QR status")
    def payment_qr_status(self, obj):
        return "Uploaded" if obj.payment_qr_image else "No QR"

    @admin.display(description="QR")
    def payment_qr_small_preview(self, obj):
        if not obj.payment_qr_image:
            return "—"

        return format_html(
            '<img src="{}" style="width:58px;height:58px;'
            'object-fit:contain;border:1px solid #ddd;'
            'border-radius:8px;background:white;padding:3px;">',
            obj.payment_qr_image.url,
        )

    @admin.display(description="Current QR preview")
    def payment_qr_preview(self, obj):
        if not obj or not obj.payment_qr_image:
            return "No payment QR uploaded yet."

        return format_html(
            '<img src="{}" style="width:280px;max-width:100%;'
            'height:auto;object-fit:contain;border:1px solid #ddd;'
            'border-radius:14px;background:white;padding:10px;">',
            obj.payment_qr_image.url,
        )