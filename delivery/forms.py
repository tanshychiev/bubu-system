from django import forms
from .models import Delivery


class DeliveryForm(forms.ModelForm):
    class Meta:
        model = Delivery
        fields = [
            "customer_name",
            "phone",
            "location",
            "total_price",
            "payment_type",
            "expected_collect",
            "actual_received",
            "delivery_fee",
            "delivery_fee_paid",
            "exchange_rate_note",
            "delivery_note",
            "delivery_date",
            "status",
        ]

        widgets = {
            "customer_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Customer name"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "Phone number"}),
            "location": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Delivery location"}),

            "total_price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "payment_type": forms.Select(attrs={"class": "form-control"}),

            "expected_collect": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "actual_received": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),

            "delivery_fee": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "delivery_fee_paid": forms.CheckboxInput(attrs={"class": "form-check-input"}),

            "exchange_rate_note": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Example: customer paid riel, $1 = 4000៛"
            }),

            "delivery_note": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "delivery_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "status": forms.Select(attrs={"class": "form-control"}),
        }