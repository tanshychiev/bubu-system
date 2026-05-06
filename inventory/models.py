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

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["item__name", "size", "color", "label", "id"]
        indexes = [
            models.Index(fields=["item", "is_active"]),
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
    def display_image(self):
        if self.image:
            return self.image
        return self.item.image

    @property
    def is_in_stock(self):
        return self.quantity > 0

    def _clean_sku_part(self, value):
        value = str(value or "").strip().upper()
        value = value.replace(" ", "")
        value = value.replace("/", "")
        value = value.replace("\\", "")
        value = value.replace("_", "")
        return value

    def build_auto_sku(self):
        type_name = ""

        if self.item and self.item.item_type:
            type_name = self.item.item_type.name

        parts = [
            self._clean_sku_part(type_name),
            self._clean_sku_part(self.item.name if self.item else ""),
            self._clean_sku_part(self.size),
            self._clean_sku_part(self.color),
            self._clean_sku_part(self.label),
            str(self.id),
        ]

        return "-".join([p for p in parts if p])

    def save(self, *args, **kwargs):
        if not self.sale_price:
            self.sale_price = self.item.sale_price

        if not self.cost_price:
            self.cost_price = self.item.cost_price

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