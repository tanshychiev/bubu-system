from decimal import Decimal

from django.db import models
from django.utils import timezone


class Delivery(models.Model):
    PAYMENT_TYPE_CHOICES = [
        ("paid", "Already Paid"),
        ("cod_collect", "COD Collect"),
        ("cod_shop", "COD Pay To Shop"),
    ]

    STATUS_CHOICES = [
        ("pending", "Pending / Next Delivery"),
        ("out", "Out For Delivery"),
        ("done", "Delivered"),
        ("cancelled", "Cancelled"),
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

    customer_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=50, blank=True)
    location = models.TextField()

    total_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))

    payment_type = models.CharField(
        max_length=20,
        choices=PAYMENT_TYPE_CHOICES,
        default="paid",
    )

    expected_collect = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    actual_received = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    lack_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))

    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    delivery_fee_paid = models.BooleanField(default=False)

    exchange_rate_note = models.CharField(max_length=150, blank=True)
    delivery_note = models.TextField(blank=True)

    delivery_date = models.DateField(default=timezone.localdate)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def calculate_lack(self):
        if self.payment_type == "cod_collect":
            return self.expected_collect - self.actual_received
        return Decimal("0.00")

    def refresh_total_price(self):
        total = sum(item.line_total for item in self.items.all())

        if total > 0:
            self.total_price = total

        if self.payment_type == "cod_collect":
            self.expected_collect = self.total_price

        self.lack_amount = self.calculate_lack()

        Delivery.objects.filter(pk=self.pk).update(
            total_price=self.total_price,
            expected_collect=self.expected_collect,
            lack_amount=self.lack_amount,
        )

    def save(self, *args, **kwargs):
        if self.payment_type == "cod_collect" and self.expected_collect == Decimal("0.00"):
            self.expected_collect = self.total_price

        self.lack_amount = self.calculate_lack()
        super().save(*args, **kwargs)

    def __str__(self):
        shop = self.branch.name if self.branch else "No Branch"
        return f"{self.customer_name} - {shop} - {self.get_payment_type_display()}"


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
        default=Decimal("0.00"),
    )

    line_total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    note = models.CharField(max_length=255, blank=True)

    def save(self, *args, **kwargs):
        self.line_total = self.qty * self.unit_price
        super().save(*args, **kwargs)

        self.delivery.refresh_total_price()

    def delete(self, *args, **kwargs):
        delivery = self.delivery
        super().delete(*args, **kwargs)

        delivery.refresh_total_price()

    def __str__(self):
        return f"{self.variant} x {self.qty}"