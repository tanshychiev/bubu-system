from django.contrib import admin
from .models import Purchase, PurchaseItem, PurchaseReceiveLog


class PurchaseItemInline(admin.TabularInline):
    model = PurchaseItem
    extra = 0
    fields = ("variant", "ordered_qty", "received_qty", "cost_price", "note")
    readonly_fields = ("received_qty",)


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "supplier",
        "status",
        "total_amount",
        "total_ordered_qty",
        "total_received_qty",
        "total_pending_qty",
        "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = ("supplier", "note", "shipping_note")
    inlines = [PurchaseItemInline]


@admin.register(PurchaseItem)
class PurchaseItemAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "purchase",
        "variant",
        "ordered_qty",
        "received_qty",
        "pending_qty",
        "cost_price",
        "total",
    )
    list_filter = ("purchase__status",)
    search_fields = (
        "purchase__supplier",
        "variant__item__name",
        "variant__sku",
        "variant__size",
        "variant__color",
        "variant__label",
    )


@admin.register(PurchaseReceiveLog)
class PurchaseReceiveLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "purchase_item",
        "qty",
        "received_by",
        "created_at",
    )
    list_filter = ("created_at",)
    search_fields = (
        "purchase_item__purchase__supplier",
        "purchase_item__variant__item__name",
        "purchase_item__variant__sku",
    )