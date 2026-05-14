from django import forms
from django.db.models import Q

from .models import Pet, PetBreed, PetSale, PetWarrantyClaim
from .models import Pet, PetBreed, PetSale, PetWarrantyClaim, PetSalePhoto


class PetBreedForm(forms.ModelForm):
    class Meta:
        model = PetBreed
        fields = [
            "pet_type",
            "name",
            "photo",
            "default_cost_price",
            "default_sale_price",
            "color_options",
            "sex_options",
            "special_type_options",
            "note",
            "is_active",
        ]


class PetForm(forms.ModelForm):
    class Meta:
        model = Pet
        fields = [
            "breed_profile",
            "pet_type",
            "breed",
            "name",
            "gender",
            "color",
            "special_type",
            "age_months_at_stock_in",
            "age_recorded_date",
            "death_date",
            "photo",
            "cost_price",
            "sale_price",
            "status",
            "note",
        ]

    def clean(self):
        cleaned = super().clean()

        breed_profile = cleaned.get("breed_profile")
        breed = cleaned.get("breed")
        age_months = cleaned.get("age_months_at_stock_in") or 0

        if not breed_profile and not breed:
            raise forms.ValidationError("Please select breed or enter breed name.")

        if age_months < 0:
            raise forms.ValidationError("Age cannot be negative.")

        return cleaned


class PetSaleForm(forms.ModelForm):
    class Meta:
        model = PetSale
        fields = [
            "sale_kind",
            "pet",
            "preorder_pet_type",
            "preorder_breed",
            "preorder_gender",
            "preorder_color",
            "preorder_special_type",
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        current_pet_id = None

        if self.instance and self.instance.pk and self.instance.pet_id:
            current_pet_id = self.instance.pet_id

        pets = (
            Pet.objects
            .select_related("breed_profile")
            .filter(status="in_stock")
            .order_by("-created_at")
        )

        if current_pet_id:
            pets = (
                Pet.objects
                .select_related("breed_profile")
                .filter(Q(status="in_stock") | Q(id=current_pet_id))
                .order_by("-created_at")
            )

        self.fields["pet"].queryset = pets

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