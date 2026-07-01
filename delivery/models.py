from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


ZERO = Decimal("0.00")


class DeliveryCompany(models.Model):
    DELIVERY_TYPE_CHOICES = [
        ("pp", "Phnom Penh"),
        ("province", "Province"),
    ]

    name = models.CharField(max_length=120)
    delivery_type = models.CharField(max_length=20, choices=DELIVERY_TYPE_CHOICES)
    phone = models.CharField(max_length=50, blank=True)
    default_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=ZERO,
        help_text="Default delivery expense used when this company is selected.",
    )
    note = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["delivery_type", "name"]

    def __str__(self):
        return f"{self.name} ({self.get_delivery_type_display()})"


class Delivery(models.Model):
    DELIVERY_AREA_CHOICES = [
        ("pp", "Phnom Penh"),
        ("province", "Province"),
    ]

    PAYMENT_TYPE_CHOICES = [
        ("paid", "Already Paid"),
        ("cod_collect", "COD Collect"),
        # Kept for old records. New forms do not offer this option.
        ("cod_shop", "COD Pay To Shop (Legacy)"),
    ]

    STATUS_CHOICES = [
        ("pending", "Pending / Next Delivery"),
        ("out", "Out For Delivery"),
        ("done", "Delivered"),
        ("failed", "Delivery Failed"),
        ("returned", "Returned + Stock Restored"),
        ("cancelled", "Cancelled"),
    ]

    COD_STATUS_CHOICES = [
        ("not_applicable", "Not Applicable"),
        ("waiting", "Waiting Money"),
        ("received", "Money Received"),
        ("short", "Short Money"),
        ("settled", "Settled"),
        ("returned", "Returned"),
    ]

    CHAT_SOURCE_CHOICES = [
        ("facebook", "Facebook"),
        ("telegram", "Telegram"),
        ("instagram", "Instagram"),
        ("tiktok", "TikTok"),
        ("call", "Call"),
        ("other", "Other"),
    ]

    branch = models.ForeignKey(
        "inventory.Branch",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="deliveries",
    )

    sale = models.OneToOneField(
        "pos.Sale",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delivery",
    )

    delivery_area = models.CharField(
        max_length=20,
        choices=DELIVERY_AREA_CHOICES,
        default="pp",
    )

    delivery_company = models.ForeignKey(
        DeliveryCompany,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deliveries",
    )

    shipper = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bubu_delivery_orders",
    )

    customer_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=50, blank=True)
    location = models.TextField()

    chat_source = models.CharField(
        max_length=30,
        choices=CHAT_SOURCE_CHOICES,
        blank=True,
    )

    social_name = models.CharField(max_length=150, blank=True)

    total_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=ZERO,
    )

    payment_type = models.CharField(
        max_length=20,
        choices=PAYMENT_TYPE_CHOICES,
        default="paid",
    )

    # COD charged to the customer. For COD this normally includes delivery fee.
    expected_collect = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=ZERO,
    )

    # Money actually transferred back to BUBU by the delivery company.
    actual_received = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=ZERO,
    )

    # expected_company_pay - actual_received
    lack_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=ZERO,
    )

    delivery_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=ZERO,
    )

    delivery_fee_paid = models.BooleanField(default=False)
    exchange_rate_note = models.CharField(max_length=150, blank=True)
    delivery_note = models.TextField(blank=True)
    delivery_date = models.DateField(default=timezone.localdate)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending",
    )

    cod_status = models.CharField(
        max_length=30,
        choices=COD_STATUS_CHOICES,
        default="not_applicable",
    )
    cod_note = models.TextField(blank=True)
    cod_received_at = models.DateTimeField(null=True, blank=True)
    cod_received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delivery_cod_received_records",
    )
    cod_settled_at = models.DateTimeField(null=True, blank=True)
    cod_settled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delivery_cod_settled_records",
    )

    delivered_at = models.DateTimeField(null=True, blank=True)
    delivered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delivery_completed_records",
    )

    failure_reason = models.TextField(blank=True)
    return_reason = models.TextField(blank=True)
    return_stock_restored = models.BooleanField(default=False)
    returned_at = models.DateTimeField(null=True, blank=True)
    returned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delivery_return_records",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-delivery_date", "-created_at"]
        indexes = [
            models.Index(fields=["delivery_area", "delivery_company"]),
            models.Index(fields=["status", "delivery_date"]),
            models.Index(fields=["payment_type", "cod_status"]),
        ]

    @property
    def cod_total(self):
        if self.payment_type in {"cod_collect", "cod_shop"}:
            return max(self.expected_collect or ZERO, ZERO)
        return ZERO

    @property
    def expected_company_pay(self):
        """COD due back to BUBU after the company keeps the delivery fee."""
        if self.payment_type not in {"cod_collect", "cod_shop"}:
            return ZERO
        return max((self.expected_collect or ZERO) - (self.delivery_fee or ZERO), ZERO)

    def calculate_lack(self):
        if self.payment_type in {"cod_collect", "cod_shop"}:
            return max(self.expected_company_pay - (self.actual_received or ZERO), ZERO)
        return ZERO

    def refresh_total_price(self):
        total = sum((item.line_total for item in self.items.all()), ZERO)

        if total > ZERO:
            self.total_price = total

        # Do not overwrite a partial balance supplied by POS.
        if self.payment_type in {"cod_collect", "cod_shop"} and not self.expected_collect:
            self.expected_collect = self.total_price

        self.lack_amount = self.calculate_lack()

        update_values = {
            "total_price": self.total_price,
            "expected_collect": self.expected_collect,
            "lack_amount": self.lack_amount,
        }
        Delivery.objects.filter(pk=self.pk).update(**update_values)

    def clean(self):
        errors = {}

        if self.delivery_company_id:
            if self.delivery_company.delivery_type != self.delivery_area:
                errors["delivery_company"] = (
                    "Selected company does not match the delivery area."
                )

        if self.delivery_area == "province" and self.payment_type != "paid":
            errors["payment_type"] = "Province delivery must be paid first."

        for field_name in (
            "total_price",
            "expected_collect",
            "actual_received",
            "delivery_fee",
        ):
            if getattr(self, field_name, ZERO) < ZERO:
                errors[field_name] = "Amount cannot be negative."

        if self.payment_type in {"cod_collect", "cod_shop"} and self.expected_collect <= ZERO:
            errors["expected_collect"] = "COD total must be greater than zero."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.payment_type not in {"cod_collect", "cod_shop"}:
            self.cod_status = "not_applicable"
            self.lack_amount = ZERO
        elif self.status == "returned":
            self.cod_status = "returned"
            self.lack_amount = ZERO
        else:
            self.lack_amount = self.calculate_lack()

            # Do not reopen a record after accounting has settled it.
            if self.cod_status != "settled":
                if (self.actual_received or ZERO) <= ZERO:
                    self.cod_status = "waiting"
                elif (self.actual_received or ZERO) < self.expected_company_pay:
                    self.cod_status = "short"
                else:
                    self.cod_status = "received"

        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = list(
                set(update_fields) | {"lack_amount", "cod_status"}
            )

        super().save(*args, **kwargs)

    def __str__(self):
        shop = self.branch.name if self.branch else "No Branch"
        company = self.delivery_company.name if self.delivery_company else "No Company"
        return f"{self.customer_name} - {shop} - {company}"


class DeliveryItem(models.Model):
    delivery = models.ForeignKey(
        Delivery,
        on_delete=models.CASCADE,
        related_name="items",
    )

    variant = models.ForeignKey(
        "inventory.ItemVariant",
        on_delete=models.PROTECT,
    )

    qty = models.PositiveIntegerField(default=1)

    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=ZERO,
    )

    line_total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=ZERO,
    )

    note = models.CharField(max_length=255, blank=True)

    def save(self, *args, **kwargs):
        self.line_total = Decimal(self.qty) * self.unit_price
        super().save(*args, **kwargs)
        self.delivery.refresh_total_price()

    def delete(self, *args, **kwargs):
        delivery = self.delivery
        super().delete(*args, **kwargs)
        delivery.refresh_total_price()

    def __str__(self):
        return f"{self.variant} x {self.qty}"
