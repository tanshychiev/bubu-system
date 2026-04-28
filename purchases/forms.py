from django import forms
from django.forms import inlineformset_factory

from inventory.models import ItemVariant
from .models import Purchase, PurchaseItem


class PurchaseForm(forms.ModelForm):
    class Meta:
        model = Purchase
        fields = ["supplier", "total_amount", "shipping_note", "note"]
        widgets = {
            "supplier": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Supplier name",
            }),
            "total_amount": forms.NumberInput(attrs={
                "class": "form-control",
                "step": "0.01",
                "placeholder": "0.00",
            }),
            "shipping_note": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 2,
                "placeholder": "Delivery / shipping note",
            }),
            "note": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 2,
                "placeholder": "Purchase note",
            }),
        }


class PurchaseItemForm(forms.ModelForm):
    class Meta:
        model = PurchaseItem
        fields = ["variant", "ordered_qty", "cost_price", "note"]
        widgets = {
            "variant": forms.Select(attrs={
                "class": "form-control variant-select",
            }),
            "ordered_qty": forms.NumberInput(attrs={
                "class": "form-control qty-input",
                "min": "1",
                "placeholder": "Qty",
            }),
            "cost_price": forms.NumberInput(attrs={
                "class": "form-control cost-input",
                "step": "0.01",
                "min": "0",
                "placeholder": "Cost",
            }),
            "note": forms.TextInput(attrs={
                "class": "form-control note-input",
                "placeholder": "Item note / plan",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["variant"].queryset = (
            ItemVariant.objects
            .select_related("item", "item__item_type")
            .filter(is_active=True)
            .order_by("item__name", "sale_price", "size", "color")
        )
        self.fields["variant"].empty_label = "Choose product / variant"

        # ✅ important: empty extra row will NOT block save
        self.fields["variant"].required = False
        self.fields["ordered_qty"].required = False
        self.fields["cost_price"].required = False
        self.fields["note"].required = False

    def clean(self):
        cleaned = super().clean()

        if cleaned.get("DELETE"):
            return cleaned

        variant = cleaned.get("variant")
        qty = cleaned.get("ordered_qty")
        cost = cleaned.get("cost_price")
        note = (cleaned.get("note") or "").strip()

        # ✅ empty row = ignore
        if not variant and not qty and cost in [None, ""] and not note:
            cleaned["EMPTY_ROW"] = True
            return cleaned

        # ✅ if row has something, require important fields
        if not variant:
            self.add_error("variant", "Please choose product / variant.")

        if not qty or qty <= 0:
            self.add_error("ordered_qty", "Qty is required.")

        if cost is None:
            self.add_error("cost_price", "Cost is required.")

        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)

        if not obj.note:
            obj.note = "No plan"

        if commit:
            obj.save()

        return obj


PurchaseItemFormSet = inlineformset_factory(
    Purchase,
    PurchaseItem,
    form=PurchaseItemForm,
    extra=1,
    can_delete=True,
    min_num=0,
    validate_min=False,
)