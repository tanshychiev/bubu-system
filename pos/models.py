from django.db import models
from django.core.exceptions import ValidationError

from customers.models import Customer
from inventory.models import Item, ItemVariant, Branch


class Sale(models.Model):
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sales",
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    change_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def balance(self):
        return self.total_amount - self.paid_amount

    @property
    def status(self):
        if self.paid_amount >= self.total_amount:
            return "Paid"
        if self.paid_amount == 0:
            return "Unpaid"
        return "Partial"

    def __str__(self):
        return f"Sale #{self.id}"


class SaleItem(models.Model):
    sale = models.ForeignKey(
        Sale,
        on_delete=models.CASCADE,
        related_name="items",
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sale_items",
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.PROTECT,
    )
    variant = models.ForeignKey(
        ItemVariant,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sale_items",
    )
    quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=2)

    @property
    def total(self):
        return self.quantity * self.price

    def clean(self):
        if self.quantity <= 0:
            raise ValidationError("Quantity must be greater than 0")

    def __str__(self):
        if self.variant:
            return f"{self.variant} x {self.quantity}"
        return f"{self.item} x {self.quantity}"


class SalePayment(models.Model):
    PAYMENT_METHODS = [
        ("cash", "Cash"),
        ("cash_usd", "Cash USD"),
        ("cash_khr", "Cash KHR"),
        ("aba", "ABA"),
        ("aba_usd", "ABA USD"),
        ("aba_khr", "ABA KHR"),
        ("bank", "Bank"),
        ("other", "Other"),
    ]

    sale = models.ForeignKey(
        Sale,
        on_delete=models.CASCADE,
        related_name="payments",
    )
    method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default="cash")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    note = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.amount <= 0:
            raise ValidationError("Payment amount must be greater than 0")

    def __str__(self):
        return f"{self.sale} - {self.method} - {self.amount}"


class POSSetting(models.Model):
    exchange_rate = models.DecimalField(max_digits=10, decimal_places=2, default=4100)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Exchange Rate: {self.exchange_rate}"


class CashCount(models.Model):
    date = models.DateField(unique=True)

    system_cash_usd = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    system_cash_khr = models.DecimalField(max_digits=14, decimal_places=0, default=0)
    system_aba_usd = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    counted_cash_usd = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    counted_cash_khr = models.DecimalField(max_digits=14, decimal_places=0, default=0)
    counted_aba_usd = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    note = models.TextField(blank=True, default="")

    counted_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    counted_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Cash Count {self.date}"