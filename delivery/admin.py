from django.contrib import admin

from .models import Delivery, DeliveryCompany, DeliveryItem


@admin.register(DeliveryCompany)
class DeliveryCompanyAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "delivery_type",
        "default_fee",
        "phone",
        "is_active",
        "updated_at",
    )
    list_filter = ("delivery_type", "is_active")
    search_fields = ("name", "phone")
    ordering = ("delivery_type", "name")


class DeliveryItemInline(admin.TabularInline):
    model = DeliveryItem
    extra = 0
    readonly_fields = ("line_total",)


@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "branch",
        "delivery_area",
        "delivery_company",
        "sale",
        "customer_name",
        "phone",
        "total_price",
        "payment_type",
        "expected_collect",
        "expected_company_pay_display",
        "actual_received",
        "lack_amount",
        "cod_status",
        "status",
        "return_stock_restored",
        "delivery_date",
    )
    list_filter = (
        "branch",
        "delivery_area",
        "delivery_company",
        "status",
        "payment_type",
        "cod_status",
        "delivery_fee_paid",
        "return_stock_restored",
        "delivery_date",
    )
    search_fields = (
        "customer_name",
        "social_name",
        "phone",
        "location",
        "delivery_note",
        "branch__name",
        "delivery_company__name",
        "sale__id",
    )
    readonly_fields = (
        "lack_amount",
        "cod_received_at",
        "cod_received_by",
        "cod_settled_at",
        "cod_settled_by",
        "delivered_at",
        "delivered_by",
        "returned_at",
        "returned_by",
        "return_stock_restored",
        "created_at",
        "updated_at",
    )
    ordering = ("-delivery_date", "-created_at")
    inlines = [DeliveryItemInline]

    @admin.display(description="Pay To Shop")
    def expected_company_pay_display(self, obj):
        return obj.expected_company_pay
