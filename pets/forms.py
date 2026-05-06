from django import forms
from .models import Pet, PetSale, PetWarrantyClaim


class PetForm(forms.ModelForm):
    class Meta:
        model = Pet
        fields = [
            "pet_type",
            "breed",
            "name",
            "gender",
            "color",
            "birth_date",
            "death_date",
            "photo",
            "cost_price",
            "sale_price",
            "status",
            "note",
        ]


class PetSaleForm(forms.ModelForm):
    class Meta:
        model = PetSale
        fields = [
            "sale_kind",
            "pet",
            "preorder_pet_type",
            "preorder_breed",
            "preorder_gender",
            "deadline",
            "customer_name",
            "phone",
            "address",
            "sale_price",
            "paid_amount",
            "warranty_days",
            "warranty_start_date",
            "sale_photo",
            "note",
        ]

    def clean(self):
        cleaned = super().clean()

        sale_kind = cleaned.get("sale_kind")
        pet = cleaned.get("pet")
        preorder_breed = cleaned.get("preorder_breed")
        sale_price = cleaned.get("sale_price") or 0
        paid_amount = cleaned.get("paid_amount") or 0

        if sale_kind == "in_stock" and not pet:
            raise forms.ValidationError("Please select an in-stock dog/cat.")

        if sale_kind == "preorder" and not preorder_breed:
            raise forms.ValidationError("Please enter breed for preorder.")

        if paid_amount > sale_price:
            raise forms.ValidationError("Paid amount cannot be bigger than full price.")

        return cleaned


class PetWarrantyClaimForm(forms.ModelForm):
    class Meta:
        model = PetWarrantyClaim
        fields = [
            "problem_note",
            "action_taken",
            "compensation_cost",
            "claim_photo",
        ]