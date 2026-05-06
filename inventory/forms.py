from django import forms

from .models import (
    Item,
    ItemType,
    UnitOption,
    ItemVariant,
    StockMovement,
    Branch,
)


class ItemTypeForm(forms.ModelForm):
    class Meta:
        model = ItemType
        fields = ["name", "emoji", "is_active"]


class UnitOptionForm(forms.ModelForm):
    class Meta:
        model = UnitOption
        fields = ["code", "name", "emoji", "is_active"]

        widgets = {
            "code": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Example: service",
            }),
            "name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Example: Service",
            }),
            "emoji": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "📏",
            }),
            "is_active": forms.CheckboxInput(attrs={
                "class": "form-check-input",
            }),
        }


class ItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = [
            "item_type",
            "name",
            "brand",
            "image",
            "unit",
            "cost_price",
            "sale_price",
            "is_active",
        ]

    def __init__(self, *args, **kwargs):
        self.can_edit_price = kwargs.pop("can_edit_price", False)
        super().__init__(*args, **kwargs)

        unit_options = UnitOption.objects.filter(is_active=True).order_by("name")

        if unit_options.exists() and "unit" in self.fields:
            self.fields["unit"].choices = [
                (unit.code, f"{unit.emoji} {unit.name}") for unit in unit_options
            ]

        if not self.can_edit_price:
            self.fields.pop("cost_price", None)
            self.fields.pop("sale_price", None)

    def clean_cost_price(self):
        price = self.cleaned_data.get("cost_price")
        if price is not None and price < 0:
            raise forms.ValidationError("Cost price cannot be negative.")
        return price

    def clean_sale_price(self):
        price = self.cleaned_data.get("sale_price")
        if price is not None and price < 0:
            raise forms.ValidationError("Sale price cannot be negative.")
        return price


class ItemVariantForm(forms.ModelForm):
    class Meta:
        model = ItemVariant
        fields = [
            "sku",
            "image",
            "size",
            "color",
            "label",
            "cost_price",
            "sale_price",
            "is_active",
        ]

    def __init__(self, *args, **kwargs):
        self.can_edit_cost_price = kwargs.pop("can_edit_cost_price", False)
        self.can_edit_price = kwargs.pop("can_edit_price", False)
        super().__init__(*args, **kwargs)

        self.fields["size"].widget.attrs.update({
            "placeholder": "Example: S, M, L"
        })
        self.fields["color"].widget.attrs.update({
            "placeholder": "Example: Red, Blue"
        })
        self.fields["label"].widget.attrs.update({
            "placeholder": "Optional: Default, Premium"
        })

        if "sale_price" in self.fields:
            self.fields["sale_price"].widget.attrs.update({
                "placeholder": "Variant sale price"
            })

        if "cost_price" in self.fields:
            self.fields["cost_price"].widget.attrs.update({
                "placeholder": "Variant cost price"
            })

        if not self.can_edit_cost_price:
            self.fields.pop("cost_price", None)

        if not self.can_edit_price:
            self.fields.pop("sale_price", None)

    def clean_sale_price(self):
        price = self.cleaned_data.get("sale_price")
        if price is not None and price < 0:
            raise forms.ValidationError("Sale price cannot be negative.")
        return price

    def clean_cost_price(self):
        price = self.cleaned_data.get("cost_price")
        if price is not None and price < 0:
            raise forms.ValidationError("Cost price cannot be negative.")
        return price


class StockMovementForm(forms.ModelForm):
    class Meta:
        model = StockMovement
        fields = [
            "branch",
            "variant",
            "movement_type",
            "quantity",
            "cost_price",
            "note",
        ]

    def __init__(self, *args, **kwargs):
        item = kwargs.pop("item", None)
        user = kwargs.pop("user", None)
        self.can_edit_cost_price = kwargs.pop("can_edit_cost_price", False)

        super().__init__(*args, **kwargs)

        self.fields["branch"].queryset = (
            Branch.objects
            .filter(is_active=True)
            .order_by("name")
        )
        self.fields["branch"].required = True

        profile = getattr(user, "staff_profile", None) if user else None

        if user and not user.is_superuser and profile and profile.branch_id:
            self.fields["branch"].queryset = Branch.objects.filter(
                id=profile.branch_id
            )
            self.fields["branch"].initial = profile.branch
            self.fields["branch"].disabled = True

        if item:
            self.fields["variant"].queryset = (
                item.variants
                .filter(is_active=True)
                .order_by("size", "color", "label", "id")
            )
        else:
            self.fields["variant"].queryset = (
                ItemVariant.objects
                .filter(is_active=True)
                .select_related("item")
                .order_by("item__name", "size", "color", "label", "id")
            )

        self.fields["variant"].label_from_instance = lambda obj: (
            f"{obj.item.name} / {obj.display_name()} / ${obj.display_price}"
        )

        if not self.can_edit_cost_price:
            self.fields.pop("cost_price", None)

    def clean_quantity(self):
        quantity = self.cleaned_data.get("quantity")

        if quantity is None:
            raise forms.ValidationError("Quantity is required.")

        if quantity <= 0:
            raise forms.ValidationError("Quantity must be greater than 0.")

        return quantity

    def clean_cost_price(self):
        price = self.cleaned_data.get("cost_price")

        if price is not None and price < 0:
            raise forms.ValidationError("Cost price cannot be negative.")

        return price


class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = ["name", "is_active"]

        widgets = {
            "name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Example: BUBU Toul Kork",
            }),
            "is_active": forms.CheckboxInput(attrs={
                "class": "form-check-input",
            }),
        }