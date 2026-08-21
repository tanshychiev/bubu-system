import re
import unicodedata

from django.db import models
from django.contrib.auth.models import User


class ItemType(models.Model):
    name = models.CharField(max_length=100, unique=True)
    emoji = models.CharField(max_length=10, blank=True, default="📦")
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.emoji} {self.name}"


class UnitOption(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    emoji = models.CharField(max_length=10, blank=True, default="📏")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.emoji} {self.name}"


class Item(models.Model):
    UNIT_CHOICES = [
        ("piece", "Piece"),
        ("bottle", "Bottle"),
        ("ml", "ML"),
        ("g", "Gram"),
        ("kg", "KG"),
        ("pack", "Pack"),
        ("box", "Box"),
        ("service", "Service"),
        ("pet", "Pet"),
    ]

    item_type = models.ForeignKey(
        ItemType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="items",
    )

    name = models.CharField(max_length=200)
    brand = models.CharField(max_length=100, blank=True, default="")
    image = models.ImageField(upload_to="items/", blank=True, null=True)
    unit = models.CharField(max_length=20, choices=UNIT_CHOICES, default="piece")

    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    sale_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def total_stock(self):
        return sum(v.quantity for v in self.variants.filter(is_active=True))

    @property
    def has_cost(self):
        return bool(self.cost_price and self.cost_price > 0)

    @property
    def cost_status(self):
        return "Already Added" if self.has_cost else "No Cost"

    @property
    def profit_per_item(self):
        return self.sale_price - self.cost_price

    def __str__(self):
        return self.name


class ItemVariant(models.Model):
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="variants",
    )

    sku = models.CharField(max_length=80, blank=True, default="")
    image = models.ImageField(upload_to="item_variants/", blank=True, null=True)

    color = models.CharField(max_length=50, blank=True, default="")
    size = models.CharField(max_length=50, blank=True, default="")
    label = models.CharField(max_length=100, blank=True, default="")

    quantity = models.IntegerField(default=0)

    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    sale_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # Controls how variants appear in Inventory, Batch Stock In and POS.
    # Staff can change this order from the item detail page.
    sort_order = models.PositiveIntegerField(default=0)

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["item__name", "sort_order", "id"]
        indexes = [
            models.Index(fields=["item", "is_active"]),
            models.Index(fields=["item", "sort_order"]),
            models.Index(fields=["sku"]),
        ]

    def display_name(self):
        parts = []

        if self.size:
            parts.append(f"Size {self.size}")

        if self.color:
            parts.append(self.color)

        if self.label:
            parts.append(self.label)

        return " / ".join(parts) if parts else "Default"

    @property
    def display_price(self):
        if self.sale_price and self.sale_price > 0:
            return self.sale_price
        return self.item.sale_price

    @property
    def display_cost(self):
        if self.cost_price and self.cost_price > 0:
            return self.cost_price
        return self.item.cost_price

    @property
    def has_cost(self):
        return bool(self.display_cost and self.display_cost > 0)

    @property
    def cost_status(self):
        return "Already Added" if self.has_cost else "No Cost"

    @property
    def display_image(self):
        if self.image:
            return self.image
        return self.item.image

    @property
    def is_in_stock(self):
        return self.quantity > 0

    @staticmethod
    def _ascii_letters(value):
        normalized = unicodedata.normalize("NFKD", str(value or ""))
        ascii_value = normalized.encode("ascii", "ignore").decode("ascii").upper()
        return re.sub(r"[^A-Z0-9]+", " ", ascii_value).strip()

    @classmethod
    def _short_code_part(cls, value, length=3, fallback=""):
        cleaned = cls._ascii_letters(value)
        words = [word for word in cleaned.split() if word]
        if not words:
            return fallback[:length]
        if len(words) >= 2:
            code = "".join(word[0] for word in words)
            if len(code) < length:
                code += words[0][1:length - len(code) + 1]
        else:
            code = words[0]
        return re.sub(r"[^A-Z0-9]", "", code)[:length]

    def build_legacy_auto_sku(self):
        """Return the exact old long automatic SKU for safe migration checks."""
        type_name = self.item.item_type.name if self.item and self.item.item_type else ""
        parts = [
            re.sub(r"[ /\\_]", "", str(type_name or "").strip().upper()),
            re.sub(r"[ /\\_]", "", str(self.item.name if self.item else "").strip().upper()),
            re.sub(r"[ /\\_]", "", str(self.size or "").strip().upper()),
            re.sub(r"[ /\\_]", "", str(self.color or "").strip().upper()),
            re.sub(r"[ /\\_]", "", str(self.label or "").strip().upper()),
            str(self.id or ""),
        ]
        return "-".join(part for part in parts if part)

    def build_auto_sku(self):
        """Build the new short, ASCII-only, scanner-friendly SKU."""
        type_name = self.item.item_type.name if self.item and self.item.item_type else "ITEM"
        variant_text = " ".join(part for part in [self.size, self.color, self.label] if part)
        source_text = variant_text or (self.item.name if self.item else "ITEM")
        id_part = str(self.id or "")

        # Keep the whole code around 8-12 characters, while preserving the ID.
        available = max(2, 12 - 4 - len(id_part))
        type_code = self._short_code_part(type_name, 4, "ITEM").ljust(4, "X")[:4]
        detail_code = self._short_code_part(source_text, available, "IT") or "IT"
        return f"{type_code}{detail_code}{id_part}"[:12]

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        if not self.sale_price:
            self.sale_price = self.item.sale_price

        if not self.cost_price:
            self.cost_price = self.item.cost_price

        if is_new and not self.sort_order:
            last_variant = (
                ItemVariant.objects
                .filter(item=self.item)
                .order_by("-sort_order", "-id")
                .first()
            )
            self.sort_order = (last_variant.sort_order if last_variant else 0) + 1

        super().save(*args, **kwargs)

        if not self.sku:
            self.sku = self.build_auto_sku()
            super().save(update_fields=["sku"])

    def __str__(self):
        return f"{self.item.name} - {self.display_name()} - ${self.display_price}"


class StockMovement(models.Model):
    MOVEMENT_TYPES = [
        ("in", "Stock In"),
        ("out", "Stock Out"),
        ("adjust", "Adjust Stock"),
        ("sale", "Sale"),
        ("transfer_in", "Transfer In"),
        ("transfer_out", "Transfer Out"),
        ("damage", "Damage / Expired / Lost"),
    ]

    branch = models.ForeignKey(
        "Branch",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="stock_movements",
    )

    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="stock_movements",
    )

    variant = models.ForeignKey(
        ItemVariant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_movements",
    )

    movement_type = models.CharField(max_length=30, choices=MOVEMENT_TYPES)
    quantity = models.IntegerField()

    before_quantity = models.IntegerField(default=0)
    after_quantity = models.IntegerField(default=0)

    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    note = models.CharField(max_length=255, blank=True, default="")

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        if is_new and self.variant and self.branch:
            stock, created = BranchStock.objects.get_or_create(
                branch=self.branch,
                variant=self.variant,
                defaults={"quantity": 0},
            )

            old_qty = int(stock.quantity or 0)
            qty = abs(int(self.quantity or 0))

            if self.movement_type in ["in", "transfer_in"]:
                new_qty = old_qty + qty

                if self.cost_price and self.cost_price > 0:
                    self.variant.cost_price = self.cost_price
                    self.variant.save(update_fields=["cost_price"])

            elif self.movement_type in ["out", "sale", "transfer_out", "damage"]:
                new_qty = old_qty - qty

            elif self.movement_type == "adjust":
                new_qty = int(self.quantity or 0)

            else:
                new_qty = old_qty

            stock.quantity = new_qty
            stock.save(update_fields=["quantity"])

            self.before_quantity = old_qty
            self.after_quantity = new_qty

        super().save(*args, **kwargs)

    @property
    def has_cost(self):
        return bool(self.cost_price and self.cost_price > 0)

    @property
    def cost_status(self):
        return "Already Added" if self.has_cost else "No Cost"

    def __str__(self):
        name = self.variant if self.variant else self.item
        branch_name = self.branch.name if self.branch else "No Branch"
        return f"{branch_name} - {name} - {self.movement_type} - {self.quantity}"


class VariantEditHistory(models.Model):
    variant = models.ForeignKey(
        ItemVariant,
        on_delete=models.CASCADE,
        related_name="edit_histories",
    )

    edited_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    field_name = models.CharField(max_length=100)
    old_value = models.CharField(max_length=255, blank=True, default="")
    new_value = models.CharField(max_length=255, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.variant} - {self.field_name}"


class ItemEditHistory(models.Model):
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="edit_histories",
    )

    edited_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    field_name = models.CharField(max_length=100)
    old_value = models.CharField(max_length=255, blank=True, default="")
    new_value = models.CharField(max_length=255, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.item} - {self.field_name}"


class Branch(models.Model):
    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)

    # Static QR shown on the customer-facing display for this branch.
    # Owner/Admin can replace it from the normal BUBU interface.
    payment_qr_image = models.ImageField(
        upload_to="branch_payment_qr/",
        blank=True,
        null=True,
        help_text="Upload the payment QR image used by this branch.",
    )

    payment_qr_label = models.CharField(
        max_length=100,
        blank=True,
        default="Scan to pay",
        help_text="Text shown below the QR on the customer display.",
    )

    payment_qr_updated_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    # These fields tell the customer display that the cashier has recorded
    # money for a completed/partial POS payment. They do not sync with ABA.
    customer_display_payment_event_id = models.PositiveBigIntegerField(
        default=0,
    )

    customer_display_payment_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )

    customer_display_payment_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    latitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
        help_text="Branch GPS latitude.",
    )

    longitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
        help_text="Branch GPS longitude.",
    )

    allowed_radius_meters = models.PositiveIntegerField(
        default=150,
        help_text="Allowed distance from branch for attendance scan.",
    )

    def __str__(self):
        return self.name


class BranchStock(models.Model):
    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="stocks",
    )
    variant = models.ForeignKey(
        ItemVariant,
        on_delete=models.CASCADE,
        related_name="branch_stocks",
    )
    quantity = models.IntegerField(default=0)

    class Meta:
        unique_together = ("branch", "variant")

    def __str__(self):
        return f"{self.branch} - {self.variant} - {self.quantity}"



# =========================================================
# SAME-PRODUCT UNIT CONVERSION
# Example: 1 Box = 10 Pills. Both units are ItemVariant children
# of the same Item, and stock remains branch-specific.
# =========================================================

class ItemUnitConversion(models.Model):
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="unit_conversions",
    )
    parent_variant = models.ForeignKey(
        ItemVariant,
        on_delete=models.PROTECT,
        related_name="unit_conversion_parent_rules",
        help_text="Larger unit, e.g. Box.",
    )
    child_variant = models.ForeignKey(
        ItemVariant,
        on_delete=models.PROTECT,
        related_name="unit_conversion_child_rules",
        help_text="Smaller unit, e.g. Pill.",
    )
    child_quantity = models.PositiveIntegerField(
        default=1,
        help_text="How many child units are inside one parent unit.",
    )
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_inventory_unit_conversions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["parent_variant__sort_order", "parent_variant_id", "child_variant_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["item", "parent_variant", "child_variant"],
                name="unique_item_parent_child_unit_conversion",
            ),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError

        errors = {}
        if self.parent_variant_id and self.parent_variant.item_id != self.item_id:
            errors["parent_variant"] = "Parent unit must belong to this product."
        if self.child_variant_id and self.child_variant.item_id != self.item_id:
            errors["child_variant"] = "Child unit must belong to this product."
        if self.parent_variant_id and self.parent_variant_id == self.child_variant_id:
            errors["child_variant"] = "Parent and child unit must be different."
        if self.child_quantity is not None and self.child_quantity < 2:
            errors["child_quantity"] = "Conversion quantity must be at least 2."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.item.name}: 1 {self.parent_variant.display_name()} = "
            f"{self.child_quantity} {self.child_variant.display_name()}"
        )


class UnitConversionHistory(models.Model):
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="unit_conversion_histories",
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.PROTECT,
        related_name="unit_conversion_histories",
    )
    rule = models.ForeignKey(
        ItemUnitConversion,
        on_delete=models.PROTECT,
        related_name="histories",
    )
    source_variant = models.ForeignKey(
        ItemVariant,
        on_delete=models.PROTECT,
        related_name="unit_conversion_source_histories",
    )
    target_variant = models.ForeignKey(
        ItemVariant,
        on_delete=models.PROTECT,
        related_name="unit_conversion_target_histories",
    )
    source_quantity = models.PositiveIntegerField()
    target_quantity = models.PositiveIntegerField()
    source_before_quantity = models.IntegerField(default=0)
    source_after_quantity = models.IntegerField(default=0)
    target_before_quantity = models.IntegerField(default=0)
    target_after_quantity = models.IntegerField(default=0)
    conversion_rate = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_unit_conversion_histories",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["branch", "item", "created_at"]),
        ]

    def __str__(self):
        return (
            f"{self.branch} - {self.item.name}: "
            f"{self.source_quantity} {self.source_variant.display_name()} -> "
            f"{self.target_quantity} {self.target_variant.display_name()}"
        )


# =========================================================
# MOBILE STOCK COUNT
# =========================================================

class StockCountSession(models.Model):
    STATUS_CHOICES = [
        ("draft", "Counting / Draft"),
        ("review", "Waiting Confirmation"),
        ("confirmed", "Confirmed"),
        ("cancelled", "Cancelled"),
    ]

    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="stock_count_sessions",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="draft",
        db_index=True,
    )

    note = models.CharField(max_length=255, blank=True, default="")

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_stock_counts",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    submitted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submitted_stock_counts",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)

    confirmed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="confirmed_stock_counts",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["branch", "status"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"Stock Count #{self.id} - {self.branch} - {self.get_status_display()}"


class StockCountLine(models.Model):
    REASON_CHOICES = [
        ("missing", "Missing item"),
        ("damaged", "Damaged"),
        ("expired", "Expired"),
        ("found_extra", "Found extra stock"),
        ("previous_wrong", "Previous count was wrong"),
        ("transfer_unrecorded", "Transfer was not recorded"),
        ("other", "Other"),
    ]

    session = models.ForeignKey(
        StockCountSession,
        on_delete=models.CASCADE,
        related_name="lines",
    )

    variant = models.ForeignKey(
        ItemVariant,
        on_delete=models.PROTECT,
        related_name="stock_count_lines",
    )

    # Quantity shown by the system when this SKU was first physically counted.
    system_quantity = models.IntegerField(default=0)
    actual_quantity = models.IntegerField(null=True, blank=True)

    reason_code = models.CharField(
        max_length=30,
        choices=REASON_CHOICES,
        blank=True,
        default="",
    )
    reason_note = models.CharField(max_length=255, blank=True, default="")

    counted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="counted_stock_lines",
    )
    counted_at = models.DateTimeField(null=True, blank=True)

    # Final live stock change at Owner/Admin confirmation time.
    applied_before_quantity = models.IntegerField(null=True, blank=True)
    applied_after_quantity = models.IntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["variant_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "variant"],
                name="unique_stock_count_session_variant",
            ),
        ]
        indexes = [
            models.Index(fields=["session", "actual_quantity"]),
            models.Index(fields=["variant"]),
        ]

    @property
    def difference(self):
        if self.actual_quantity is None:
            return 0
        return int(self.actual_quantity) - int(self.system_quantity or 0)

    @property
    def is_counted(self):
        return self.actual_quantity is not None

    @property
    def is_correct(self):
        return self.is_counted and self.difference == 0

    def __str__(self):
        return f"{self.session} - {self.variant}"
