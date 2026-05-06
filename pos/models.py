from django.db import models
from django.core.exceptions import ValidationError

from customers.models import Customer
from inventory.models import Item, ItemVariant, Branch


class Sale(models.Model):
    SALE_TYPE_CHOICES = [
        ("walk_in", "Walk-in"),
        ("prepare_delivery", "Prepare for Delivery"),
    ]

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

    sale_type = models.CharField(
        max_length=30,
        choices=SALE_TYPE_CHOICES,
        default="walk_in",
    )
    delivery_created = models.BooleanField(default=False)

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

    def clean(self):
        if self.total_amount < 0:
            raise ValidationError("Total amount cannot be negative.")

        if self.paid_amount < 0:
            raise ValidationError("Paid amount cannot be negative.")

        if self.change_amount < 0:
            raise ValidationError("Change amount cannot be negative.")

    def __str__(self):
        branch_name = self.branch.name if self.branch else "No Branch"
        return f"Sale #{self.id} - {branch_name}"


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
            raise ValidationError("Quantity must be greater than 0.")

        if self.price < 0:
            raise ValidationError("Price cannot be negative.")

        if self.sale and self.branch and self.sale.branch_id:
            if self.branch_id != self.sale.branch_id:
                raise ValidationError("Sale item branch must match sale branch.")

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
            raise ValidationError("Payment amount must be greater than 0.")

    def __str__(self):
        return f"{self.sale} - {self.method} - {self.amount}"


class POSSetting(models.Model):
    exchange_rate = models.DecimalField(max_digits=10, decimal_places=2, default=4100)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Exchange Rate: {self.exchange_rate}"


class CashCount(models.Model):
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cash_counts",
    )

    date = models.DateField()

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

    class Meta:
        unique_together = ("branch", "date")
        ordering = ["-date", "branch__name"]

    def clean(self):
        if self.system_cash_usd < 0:
            raise ValidationError("System cash USD cannot be negative.")

        if self.system_cash_khr < 0:
            raise ValidationError("System cash KHR cannot be negative.")

        if self.system_aba_usd < 0:
            raise ValidationError("System ABA USD cannot be negative.")

        if self.counted_cash_usd < 0:
            raise ValidationError("Counted cash USD cannot be negative.")

        if self.counted_cash_khr < 0:
            raise ValidationError("Counted cash KHR cannot be negative.")

        if self.counted_aba_usd < 0:
            raise ValidationError("Counted ABA USD cannot be negative.")

    def __str__(self):
        branch_name = self.branch.name if self.branch else "No Branch"
        return f"Cash Count {branch_name} - {self.date}"