from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from inventory.models import ItemVariant, StockMovement, Branch, BranchStock


class Purchase(models.Model):
    STATUS_CHOICES = [
        ("ordered", "Ordered"),
        ("partial", "Partial Received"),
        ("received", "Fully Received"),
        ("cancelled", "Cancelled"),
    ]

    supplier = models.CharField(max_length=150)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    shipping_note = models.TextField(blank=True, default="")
    note = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="ordered")
    created_at = models.DateTimeField(auto_now_add=True)

    def refresh_status(self):
        items = self.items.all()

        if not items.exists():
            self.status = "ordered"
        elif all(item.received_qty >= item.ordered_qty for item in items):
            self.status = "received"
        elif any(item.received_qty > 0 for item in items):
            self.status = "partial"
        else:
            self.status = "ordered"

        self.save(update_fields=["status"])

    @property
    def total_ordered_qty(self):
        return sum(item.ordered_qty for item in self.items.all())

    @property
    def total_received_qty(self):
        return sum(item.received_qty for item in self.items.all())

    @property
    def total_pending_qty(self):
        return sum(item.pending_qty for item in self.items.all())

    @property
    def total_allocated_qty(self):
        return sum(item.allocated_qty for item in self.items.all())

    @property
    def total_unallocated_qty(self):
        return sum(item.unallocated_qty for item in self.items.all())

    def __str__(self):
        return f"Purchase #{self.id}"


class PurchaseItem(models.Model):
    purchase = models.ForeignKey(
        Purchase,
        on_delete=models.CASCADE,
        related_name="items",
    )

    variant = models.ForeignKey(
        ItemVariant,
        on_delete=models.PROTECT,
        related_name="purchase_items",
        null=True,
        blank=True,
    )

    ordered_qty = models.PositiveIntegerField(default=1)
    received_qty = models.PositiveIntegerField(default=0)

    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    note = models.CharField(max_length=255, blank=True, default="")

    @property
    def pending_qty(self):
        return max(self.ordered_qty - self.received_qty, 0)

    @property
    def planned_qty(self):
        return sum(plan.qty for plan in self.branch_plans.all())

    @property
    def unplanned_qty(self):
        return max(self.ordered_qty - self.planned_qty, 0)

    @property
    def allocated_qty(self):
        return sum(allocation.qty for allocation in self.branch_allocations.all())

    @property
    def unallocated_qty(self):
        return max(self.received_qty - self.allocated_qty, 0)

    @property
    def total(self):
        return self.ordered_qty * self.cost_price

    @property
    def receive_progress_percent(self):
        if self.ordered_qty <= 0:
            return 0
        return min(int((self.received_qty / self.ordered_qty) * 100), 100)

    @property
    def allocate_progress_percent(self):
        if self.received_qty <= 0:
            return 0
        return min(int((self.allocated_qty / self.received_qty) * 100), 100)

    def __str__(self):
        if self.variant:
            return f"{self.variant} x {self.ordered_qty}"
        return f"Purchase Item #{self.id} x {self.ordered_qty}"


class PurchaseBranchPlan(models.Model):
    purchase_item = models.ForeignKey(
        PurchaseItem,
        on_delete=models.CASCADE,
        related_name="branch_plans",
    )

    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="purchase_branch_plans",
    )

    qty = models.PositiveIntegerField()

    note = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["branch__name", "id"]
        unique_together = ("purchase_item", "branch")

    @property
    def received_qty(self):
        return sum(
            allocation.qty
            for allocation in self.purchase_item.branch_allocations.filter(branch=self.branch)
        )

    @property
    def remaining_qty(self):
        return max(self.qty - self.received_qty, 0)

    @property
    def progress_percent(self):
        if self.qty <= 0:
            return 0
        return min(int((self.received_qty / self.qty) * 100), 100)

    def clean(self):
        if self.purchase_item_id:
            other_plans_total = (
                self.purchase_item.branch_plans
                .exclude(pk=self.pk)
                .aggregate(total=models.Sum("qty"))["total"] or 0
            )

            if other_plans_total + self.qty > self.purchase_item.ordered_qty:
                raise ValidationError({
                    "qty": f"Plan total cannot be more than ordered qty: {self.purchase_item.ordered_qty}"
                })

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Plan {self.branch} {self.qty} - {self.purchase_item}"


class PurchaseReceiveLog(models.Model):
    purchase_item = models.ForeignKey(
        PurchaseItem,
        on_delete=models.CASCADE,
        related_name="receive_logs",
    )

    qty = models.PositiveIntegerField()

    received_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    note = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def clean(self):
        if self.purchase_item_id and self.qty > self.purchase_item.pending_qty:
            raise ValidationError({
                "qty": f"Cannot receive more than pending qty: {self.purchase_item.pending_qty}"
            })

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        if is_new:
            self.full_clean()

        purchase_item = self.purchase_item
        real_qty = min(self.qty, purchase_item.pending_qty)

        super().save(*args, **kwargs)

        if not is_new:
            return

        if real_qty <= 0:
            return

        purchase_item.received_qty += real_qty
        purchase_item.save(update_fields=["received_qty"])

        purchase_item.purchase.refresh_status()

    def __str__(self):
        return f"Supplier Receive {self.qty} - {self.purchase_item}"


class PurchaseBranchAllocation(models.Model):
    purchase_item = models.ForeignKey(
        PurchaseItem,
        on_delete=models.CASCADE,
        related_name="branch_allocations",
    )

    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="purchase_allocations",
    )

    qty = models.PositiveIntegerField()

    allocated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    note = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def clean(self):
        if self.purchase_item_id and self.qty > self.purchase_item.unallocated_qty:
            raise ValidationError({
                "qty": f"Cannot allocate more than unallocated qty: {self.purchase_item.unallocated_qty}"
            })

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        if is_new:
            self.full_clean()

        super().save(*args, **kwargs)

        if not is_new:
            return

        purchase_item = self.purchase_item

        if not purchase_item.variant:
            return

        stock, created = BranchStock.objects.get_or_create(
            branch=self.branch,
            variant=purchase_item.variant,
            defaults={"quantity": 0},
        )

        stock.quantity += self.qty
        stock.save(update_fields=["quantity"])

        StockMovement.objects.create(
            item=purchase_item.variant.item,
            variant=purchase_item.variant,
            movement_type="in",
            quantity=self.qty,
            cost_price=purchase_item.cost_price,
            note=f"Allocated from purchase #{purchase_item.purchase.id} to {self.branch.name}",
            created_by=self.allocated_by,
        )

    def __str__(self):
        return f"Allocate {self.branch} +{self.qty} - {self.purchase_item}"


class BranchTransfer(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("received", "Received"),
        ("cancelled", "Cancelled"),
    ]

    purchase_item = models.ForeignKey(
        PurchaseItem,
        on_delete=models.CASCADE,
        related_name="branch_transfers",
    )

    from_branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="purchase_transfer_from",
    )

    to_branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="purchase_transfer_to",
    )

    qty = models.PositiveIntegerField()

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")

    sent_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_transfers_sent",
    )

    received_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_transfers_received",
    )

    note = models.CharField(max_length=255, blank=True, default="")
    sent_at = models.DateTimeField(auto_now_add=True)
    received_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-sent_at", "-id"]

    def clean(self):
        if self.from_branch_id and self.to_branch_id and self.from_branch_id == self.to_branch_id:
            raise ValidationError("From branch and To branch cannot be the same.")

        if self.pk is None and self.purchase_item_id and self.from_branch_id:
            if not self.purchase_item.variant:
                return

            stock = BranchStock.objects.filter(
                branch=self.from_branch,
                variant=self.purchase_item.variant,
            ).first()

            current_qty = stock.quantity if stock else 0

            if self.qty > current_qty:
                raise ValidationError({
                    "qty": f"Not enough stock in {self.from_branch.name}. Current stock: {current_qty}"
                })

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        if is_new:
            self.full_clean()

        super().save(*args, **kwargs)

        if not is_new:
            return

        if not self.purchase_item.variant:
            return

        from_stock, created = BranchStock.objects.get_or_create(
            branch=self.from_branch,
            variant=self.purchase_item.variant,
            defaults={"quantity": 0},
        )

        from_stock.quantity -= self.qty
        from_stock.save(update_fields=["quantity"])

        StockMovement.objects.create(
            item=self.purchase_item.variant.item,
            variant=self.purchase_item.variant,
            movement_type="out",
            quantity=self.qty,
            cost_price=self.purchase_item.cost_price,
            note=f"Transfer to {self.to_branch.name} from purchase #{self.purchase_item.purchase.id}",
            created_by=self.sent_by,
        )

    def mark_received(self, user=None):
        if self.status != "pending":
            return

        if not self.purchase_item.variant:
            return

        to_stock, created = BranchStock.objects.get_or_create(
            branch=self.to_branch,
            variant=self.purchase_item.variant,
            defaults={"quantity": 0},
        )

        to_stock.quantity += self.qty
        to_stock.save(update_fields=["quantity"])

        StockMovement.objects.create(
            item=self.purchase_item.variant.item,
            variant=self.purchase_item.variant,
            movement_type="in",
            quantity=self.qty,
            cost_price=self.purchase_item.cost_price,
            note=f"Transfer received from {self.from_branch.name} for purchase #{self.purchase_item.purchase.id}",
            created_by=user,
        )

        from django.utils import timezone
        self.status = "received"
        self.received_by = user
        self.received_at = timezone.now()
        self.save(update_fields=["status", "received_by", "received_at"])

    def __str__(self):
        return f"Transfer {self.from_branch} → {self.to_branch} {self.qty}"
    
class PurchaseEditLog(models.Model):
    purchase = models.ForeignKey(
        Purchase,
        on_delete=models.CASCADE,
        related_name="edit_logs",
    )

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    action = models.CharField(max_length=100)
    field_name = models.CharField(max_length=100, blank=True, default="")
    old_value = models.TextField(blank=True, default="")
    new_value = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.purchase} edited {self.field_name}"    