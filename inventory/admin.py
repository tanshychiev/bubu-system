from django.contrib import admin
from .models import Item, ItemType, ItemVariant, StockMovement


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