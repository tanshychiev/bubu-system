from django import forms

from .models import Item, ItemType, ItemVariant, StockMovement, Branch


class ItemTypeForm(forms.ModelForm):
    class Meta:
        model = ItemType
        fields = ["name", "emoji", "is_active"]


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
            "quantity",
            "cost_price",
            "sale_price",
            "is_active",
        ]

    def __init__(self, *args, **kwargs):
        self.can_edit_cost_price = kwargs.pop("can_edit_cost_price", False)
        self.can_edit_price = kwargs.pop("can_edit_price", False)
        super().__init__(*args, **kwargs)

        self.fields["size"].widget.attrs.update({"placeholder": "Example: S, M, L"})
        self.fields["color"].widget.attrs.update({"placeholder": "Example: Red, Blue"})
        self.fields["label"].widget.attrs.update({"placeholder": "Optional: Default, Premium"})
        self.fields["quantity"].widget.attrs.update({"placeholder": "Old stock qty"})

        if "sale_price" in self.fields:
            self.fields["sale_price"].widget.attrs.update({"placeholder": "Variant sale price"})

        if "cost_price" in self.fields:
            self.fields["cost_price"].widget.attrs.update({"placeholder": "Variant cost price"})

        if not self.can_edit_cost_price:
            self.fields.pop("cost_price", None)

        if not self.can_edit_price:
            self.fields.pop("sale_price", None)

    def clean_quantity(self):
        qty = self.cleaned_data.get("quantity")
        if qty is None:
            return 0
        return qty

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
            "variant",
            "movement_type",
            "quantity",
            "cost_price",
            "note",
        ]

    def __init__(self, *args, **kwargs):
        item = kwargs.pop("item", None)
        self.can_edit_cost_price = kwargs.pop("can_edit_cost_price", False)
        super().__init__(*args, **kwargs)

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
            f"{obj.item.name} / {obj.display_name()} / ${obj.display_price} / Old Stock: {obj.quantity}"
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