from decimal import Decimal

from django import forms

from .models import (
    Item,
    ItemType,
    UnitOption,
    ItemVariant,
    StockMovement,
    Branch,
)


class WriteOnlyCostMixin:
    """
    Owner/Admin sees the existing amount.
    Staff gets a blank cost input and only a status in the template.
    Leaving the blank staff field unchanged preserves the old amount.
    """

    cost_field_name = "cost_price"

    def setup_cost_access(self, can_edit_cost_price, can_view_cost_price):
        self.can_edit_cost_price = bool(can_edit_cost_price)
        self.can_view_cost_price = bool(can_view_cost_price)

        field_name = self.cost_field_name
        self._original_cost = Decimal("0.00")

        if self.instance and getattr(self.instance, "pk", None):
            self._original_cost = getattr(self.instance, field_name, Decimal("0.00")) or Decimal("0.00")

        self.cost_status = "Already Added" if self._original_cost > 0 else "No Cost"

        if not self.can_edit_cost_price:
            self.fields.pop(field_name, None)
            return

        field = self.fields[field_name]
        field.required = False
        field.widget.attrs.update({
            "autocomplete": "off",
            "data-cost-status": self.cost_status,
        })

        if not self.can_view_cost_price:
            self.initial[field_name] = ""
            field.initial = ""
            field.widget.attrs["placeholder"] = (
                "Enter a new cost"
                if self.cost_status == "No Cost"
                else "Cost already added — enter only to replace"
            )

    def clean_write_only_cost(self):
        field_name = self.cost_field_name

        if field_name not in self.fields:
            return self._original_cost

        value = self.cleaned_data.get(field_name)

        if value is None:
            return self._original_cost

        if value < 0:
            raise forms.ValidationError("Cost price cannot be negative.")

        return value


class ItemTypeForm(forms.ModelForm):
    class Meta:
        model = ItemType
        fields = ["name", "emoji", "is_active"]


class UnitOptionForm(forms.ModelForm):
    class Meta:
        model = UnitOption
        fields = ["code", "name", "emoji", "is_active"]
        widgets = {
            "code": forms.TextInput(attrs={"class": "form-control", "placeholder": "Example: service"}),
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Example: Service"}),
            "emoji": forms.TextInput(attrs={"class": "form-control", "placeholder": "📏"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class ItemForm(WriteOnlyCostMixin, forms.ModelForm):
    cost_field_name = "cost_price"

    class Meta:
        model = Item
        fields = [
            "item_type", "name", "brand", "image", "unit",
            "cost_price", "sale_price", "is_active",
        ]

    def __init__(self, *args, **kwargs):
        can_edit_cost_price = kwargs.pop("can_edit_cost_price", False)
        can_view_cost_price = kwargs.pop("can_view_cost_price", False)
        can_edit_sale_price = kwargs.pop("can_edit_sale_price", True)
        # Backward compatibility with the old view argument.
        old_can_edit_price = kwargs.pop("can_edit_price", None)
        if old_can_edit_price is not None:
            can_edit_cost_price = old_can_edit_price
            can_edit_sale_price = old_can_edit_price

        super().__init__(*args, **kwargs)

        unit_options = UnitOption.objects.filter(is_active=True).order_by("name")
        if unit_options.exists() and "unit" in self.fields:
            self.fields["unit"].choices = [
                (unit.code, f"{unit.emoji} {unit.name}") for unit in unit_options
            ]

        self.setup_cost_access(can_edit_cost_price, can_view_cost_price)

        if not can_edit_sale_price:
            self.fields.pop("sale_price", None)

    def clean_cost_price(self):
        return self.clean_write_only_cost()

    def clean_sale_price(self):
        price = self.cleaned_data.get("sale_price")
        if price is not None and price < 0:
            raise forms.ValidationError("Sale price cannot be negative.")
        return price


class ItemVariantForm(WriteOnlyCostMixin, forms.ModelForm):
    cost_field_name = "cost_price"

    class Meta:
        model = ItemVariant
        fields = [
            "sku", "image", "size", "color", "label",
            "cost_price", "sale_price", "is_active",
        ]

    def __init__(self, *args, **kwargs):
        can_edit_cost_price = kwargs.pop("can_edit_cost_price", False)
        can_view_cost_price = kwargs.pop("can_view_cost_price", False)
        can_edit_sale_price = kwargs.pop("can_edit_sale_price", kwargs.pop("can_edit_price", True))
        super().__init__(*args, **kwargs)

        self.fields["size"].widget.attrs.update({"placeholder": "Example: S, M, L"})
        self.fields["color"].widget.attrs.update({"placeholder": "Example: Red, Blue"})
        self.fields["label"].widget.attrs.update({"placeholder": "Optional: Default, Premium"})

        if "sale_price" in self.fields:
            self.fields["sale_price"].widget.attrs.update({"placeholder": "Variant sale price"})

        if "cost_price" in self.fields:
            self.fields["cost_price"].widget.attrs.update({"placeholder": "Variant cost price"})

        self.setup_cost_access(can_edit_cost_price, can_view_cost_price)

        if not can_edit_sale_price:
            self.fields.pop("sale_price", None)

    def clean_cost_price(self):
        return self.clean_write_only_cost()

    def clean_sale_price(self):
        price = self.cleaned_data.get("sale_price")
        if price is not None and price < 0:
            raise forms.ValidationError("Sale price cannot be negative.")
        return price


class StockMovementForm(WriteOnlyCostMixin, forms.ModelForm):
    cost_field_name = "cost_price"

    class Meta:
        model = StockMovement
        fields = ["branch", "variant", "movement_type", "quantity", "cost_price", "note"]

    def __init__(self, *args, **kwargs):
        item = kwargs.pop("item", None)
        user = kwargs.pop("user", None)
        can_edit_cost_price = kwargs.pop("can_edit_cost_price", False)
        can_view_cost_price = kwargs.pop("can_view_cost_price", False)
        super().__init__(*args, **kwargs)

        self.fields["branch"].queryset = Branch.objects.filter(is_active=True).order_by("name")
        self.fields["branch"].required = True

        profile = getattr(user, "staff_profile", None) if user else None
        if user and not user.is_superuser and profile and profile.branch_id:
            self.fields["branch"].queryset = Branch.objects.filter(id=profile.branch_id)
            self.fields["branch"].initial = profile.branch
            self.fields["branch"].disabled = True

        if item:
            self.fields["variant"].queryset = item.variants.filter(is_active=True).order_by(
                "size", "color", "label", "id"
            )
        else:
            self.fields["variant"].queryset = ItemVariant.objects.filter(
                is_active=True
            ).select_related("item").order_by(
                "item__name", "size", "color", "label", "id"
            )

        self.fields["variant"].label_from_instance = lambda obj: (
            f"{obj.item.name} / {obj.display_name()} / ${obj.display_price}"
        )

        self.setup_cost_access(can_edit_cost_price, can_view_cost_price)

    def clean_quantity(self):
        quantity = self.cleaned_data.get("quantity")
        if quantity is None:
            raise forms.ValidationError("Quantity is required.")
        if quantity <= 0:
            raise forms.ValidationError("Quantity must be greater than 0.")
        return quantity

    def clean_cost_price(self):
        return self.clean_write_only_cost()


class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = ["name", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Example: BUBU Toul Kork"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
