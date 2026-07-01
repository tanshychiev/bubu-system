from django import forms
from django.db.models import Q

from .models import Delivery, DeliveryCompany


class DeliveryForm(forms.ModelForm):
    class Meta:
        model = Delivery
        fields = [
            "branch",
            "delivery_area",
            "delivery_company",
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
            "branch": forms.Select(attrs={"class": "form-control"}),
            "delivery_area": forms.Select(attrs={"class": "form-control", "id": "id_delivery_area"}),
            "delivery_company": forms.Select(attrs={"class": "form-control", "id": "id_delivery_company"}),
            "customer_name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Customer name or social media name",
                    "autocomplete": "off",
                }
            ),
            "phone": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Customer phone number",
                    "autocomplete": "off",
                    "inputmode": "tel",
                }
            ),
            "location": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Delivery location / address / map note",
                }
            ),
            "total_price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "payment_type": forms.Select(attrs={"class": "form-control", "id": "id_payment_type"}),
            "expected_collect": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "actual_received": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "delivery_fee": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0", "inputmode": "decimal"}),
            "delivery_fee_paid": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "exchange_rate_note": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Example: company paid by another rate",
                }
            ),
            "delivery_note": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "delivery_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "status": forms.Select(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["phone"].required = True
        self.fields["location"].required = True

        company_filter = Q(is_active=True)
        if self.instance and self.instance.pk and self.instance.delivery_company_id:
            company_filter |= Q(pk=self.instance.delivery_company_id)

        self.fields["delivery_company"].queryset = (
            DeliveryCompany.objects.filter(company_filter)
            .distinct()
            .order_by("delivery_type", "name")
        )
        self.fields["delivery_company"].required = True

        # New forms use only the two real payment choices.
        payment_choices = [
            ("paid", "Already Paid"),
            ("cod_collect", "COD / Not Paid Yet"),
        ]
        if self.instance and self.instance.pk and self.instance.payment_type == "cod_shop":
            payment_choices.append(("cod_shop", "COD Pay To Shop (Legacy)"))
        self.fields["payment_type"].choices = payment_choices

    def clean(self):
        cleaned = super().clean()
        area = cleaned.get("delivery_area")
        company = cleaned.get("delivery_company")
        payment_type = cleaned.get("payment_type")

        if company and area and company.delivery_type != area:
            self.add_error(
                "delivery_company",
                "Choose a company from the same delivery area.",
            )

        if area == "province" and payment_type != "paid":
            self.add_error(
                "payment_type",
                "Province delivery must be paid first.",
            )

        return cleaned


class DeliveryCompanyForm(forms.ModelForm):
    class Meta:
        model = DeliveryCompany
        fields = [
            "name",
            "delivery_type",
            "phone",
            "default_fee",
            "note",
            "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Example: DS EXPRESS"}),
            "delivery_type": forms.Select(),
            "phone": forms.TextInput(attrs={"placeholder": "Optional phone number"}),
            "default_fee": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "note": forms.Textarea(attrs={"rows": 4, "placeholder": "Optional company note"}),
            "is_active": forms.CheckboxInput(),
        }
