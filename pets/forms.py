from decimal import Decimal

from django import forms
from django.db.models import Q

from inventory.models import Branch

from .models import (
    Pet,
    PetBreed,
    PetSale,
    PetWarrantyClaim,
)


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

        widgets = {
            "pet_type": forms.Select(attrs={"class": "form-control"}),
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "photo": forms.ClearableFileInput(attrs={
                "class": "form-control",
                "accept": "image/*",
            }),
            "default_cost_price": forms.NumberInput(attrs={
                "class": "form-control",
                "step": "0.01",
                "min": "0",
                "inputmode": "decimal",
            }),
            "default_sale_price": forms.NumberInput(attrs={
                "class": "form-control",
                "step": "0.01",
                "min": "0",
                "inputmode": "decimal",
            }),
            "color_options": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Example: White, Cream, Brown, Black",
            }),
            "sex_options": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Example: Male,Female",
            }),
            "special_type_options": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Example: Teacup, Mini, Standard",
            }),
            "note": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Breed note...",
            }),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class PetForm(forms.ModelForm):
    class Meta:
        model = Pet
        fields = [
            "branch",
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

        widgets = {
            "branch": forms.Select(attrs={"class": "form-control"}),
            "breed_profile": forms.Select(attrs={"class": "form-control"}),
            "pet_type": forms.Select(attrs={"class": "form-control"}),
            "breed": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Breed name if no breed profile",
            }),
            "name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Pet name / nickname",
            }),
            "gender": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Male / Female",
            }),
            "color": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "White, Cream, Brown...",
            }),
            "special_type": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Teacup, Mini, Show Grade...",
            }),
            "age_months_at_stock_in": forms.NumberInput(attrs={
                "class": "form-control",
                "min": "0",
                "inputmode": "numeric",
            }),
            "age_recorded_date": forms.DateInput(attrs={
                "class": "form-control",
                "type": "date",
            }),
            "death_date": forms.DateInput(attrs={
                "class": "form-control",
                "type": "date",
            }),
            "photo": forms.ClearableFileInput(attrs={
                "class": "form-control",
                "accept": "image/*",
            }),
            "cost_price": forms.NumberInput(attrs={
                "class": "form-control",
                "step": "0.01",
                "min": "0",
                "inputmode": "decimal",
            }),
            "sale_price": forms.NumberInput(attrs={
                "class": "form-control",
                "step": "0.01",
                "min": "0",
                "inputmode": "decimal",
            }),
            "status": forms.Select(attrs={"class": "form-control"}),
            "note": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Pet note...",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["branch"].queryset = Branch.objects.filter(
            is_active=True,
        ).order_by("name")
        self.fields["branch"].required = False
        self.fields["branch"].empty_label = "Select Branch / Shop"

        self.fields["breed_profile"].queryset = PetBreed.objects.filter(
            is_active=True,
        ).order_by("pet_type", "name")
        self.fields["breed_profile"].required = False
        self.fields["breed_profile"].empty_label = "Select Breed Master"

        self.fields["breed"].required = False
        self.fields["death_date"].required = False
        self.fields["photo"].required = False
        self.fields["note"].required = False

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
            "discount_amount",
            "paid_amount",
            "warranty_days",
            "warranty_start_date",
            "sale_photo",
            "note",
        ]

        widgets = {
            "sale_kind": forms.Select(attrs={"class": "form-control"}),
            "pet": forms.Select(attrs={"class": "form-control"}),
            "preorder_pet_type": forms.Select(attrs={"class": "form-control"}),
            "preorder_breed": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Breed",
            }),
            "preorder_gender": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Male / Female",
            }),
            "preorder_color": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Color",
            }),
            "preorder_special_type": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Special type",
            }),
            "deadline": forms.DateInput(attrs={
                "class": "form-control",
                "type": "date",
            }),
            "customer_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Customer name",
            }),
            "phone": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Phone number",
            }),
            "address": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 2,
                "placeholder": "Customer location",
            }),
            "sale_price": forms.NumberInput(attrs={
                "class": "form-control",
                "step": "0.01",
                "min": "0",
                "inputmode": "decimal",
            }),
            "discount_amount": forms.NumberInput(attrs={
                "class": "form-control",
                "step": "0.01",
                "min": "0",
                "inputmode": "decimal",
            }),
            "paid_amount": forms.NumberInput(attrs={
                "class": "form-control",
                "step": "0.01",
                "min": "0",
                "inputmode": "decimal",
            }),
            "warranty_days": forms.NumberInput(attrs={
                "class": "form-control",
                "min": "0",
                "inputmode": "numeric",
            }),
            "warranty_start_date": forms.DateInput(attrs={
                "class": "form-control",
                "type": "date",
            }),
            "sale_photo": forms.ClearableFileInput(attrs={
                "class": "form-control",
                "accept": "image/*",
            }),
            "note": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Sale note...",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        current_pet_id = None

        if self.instance and self.instance.pk and self.instance.pet_id:
            current_pet_id = self.instance.pet_id

        pets = (
            Pet.objects
            .select_related("breed_profile", "branch")
            .filter(status="in_stock")
            .order_by("branch__name", "pet_type", "breed_profile__name", "breed", "name")
        )

        if current_pet_id:
            pets = (
                Pet.objects
                .select_related("breed_profile", "branch")
                .filter(Q(status="in_stock") | Q(id=current_pet_id))
                .order_by("branch__name", "pet_type", "breed_profile__name", "breed", "name")
            )

        self.fields["pet"].queryset = pets
        self.fields["pet"].required = False
        self.fields["pet"].empty_label = "Select In-stock Pet"

        self.fields["deadline"].required = False
        self.fields["phone"].required = False
        self.fields["address"].required = False
        self.fields["discount_amount"].required = False
        self.fields["warranty_start_date"].required = False
        self.fields["sale_photo"].required = False
        self.fields["note"].required = False

    def clean(self):
        cleaned = super().clean()

        sale_kind = cleaned.get("sale_kind")
        pet = cleaned.get("pet")
        preorder_breed = cleaned.get("preorder_breed")

        sale_price = cleaned.get("sale_price") or Decimal("0.00")
        discount_amount = cleaned.get("discount_amount") or Decimal("0.00")
        paid_amount = cleaned.get("paid_amount") or Decimal("0.00")
        final_price = sale_price - discount_amount

        if sale_kind == "in_stock" and not pet:
            raise forms.ValidationError("Please select an in-stock dog/cat.")

        if sale_kind == "preorder" and not preorder_breed:
            raise forms.ValidationError("Please enter breed for preorder.")

        if discount_amount < 0:
            raise forms.ValidationError("Discount cannot be negative.")

        if discount_amount > sale_price:
            raise forms.ValidationError("Discount cannot be bigger than full price.")

        if paid_amount > final_price:
            raise forms.ValidationError("Paid amount cannot be bigger than final price after discount.")

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

        widgets = {
            "problem_note": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Problem note...",
            }),
            "action_taken": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Action taken...",
            }),
            "compensation_cost": forms.NumberInput(attrs={
                "class": "form-control",
                "step": "0.01",
                "min": "0",
                "inputmode": "decimal",
            }),
            "claim_photo": forms.ClearableFileInput(attrs={
                "class": "form-control",
                "accept": "image/*",
            }),
        }
