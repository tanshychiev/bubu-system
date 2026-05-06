from datetime import timedelta

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class Pet(models.Model):
    TYPE_CHOICES = [
        ("dog", "Dog"),
        ("cat", "Cat"),
        ("other", "Other"),
    ]

    STATUS_CHOICES = [
        ("in_stock", "In Stock"),
        ("reserved", "Reserved / Deposit"),
        ("sold", "Sold"),
        ("preorder", "Preorder"),
        ("sick", "Sick"),
        ("dead", "Dead"),
        ("cancelled", "Cancelled"),
    ]

    pet_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default="dog")
    breed = models.CharField(max_length=120)
    name = models.CharField(max_length=120, blank=True)
    gender = models.CharField(max_length=30, blank=True)
    color = models.CharField(max_length=80, blank=True)

    birth_date = models.DateField(null=True, blank=True)
    death_date = models.DateField(null=True, blank=True)

    photo = models.ImageField(upload_to="pets/", blank=True, null=True)

    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    sale_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="in_stock")
    note = models.TextField(blank=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_pets",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def latest_vaccine(self):
        return self.vaccines.order_by("-vaccine_date", "-id").first()

    @property
    def next_vaccine_date(self):
        latest = self.vaccines.exclude(
            next_recommended_date__isnull=True,
        ).order_by("-next_recommended_date", "-id").first()

        if latest:
            return latest.next_recommended_date

        return None

    def __str__(self):
        return f"{self.get_pet_type_display()} - {self.breed} - {self.get_status_display()}"


class PetVaccine(models.Model):
    pet = models.ForeignKey(Pet, on_delete=models.CASCADE, related_name="vaccines")
    vaccine_no = models.PositiveIntegerField(default=1)

    vaccine_name = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text="Example: Vaccine 1, Vaccine 2, 5-in-1, Rabies",
    )

    vaccine_date = models.DateField(null=True, blank=True)
    next_recommended_date = models.DateField(null=True, blank=True)

    note = models.CharField(max_length=255, blank=True, default="")

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_pet_vaccines",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["vaccine_no", "id"]

    def __str__(self):
        return f"{self.pet} - Vaccine {self.vaccine_no}"


class PetSale(models.Model):
    SALE_KIND_CHOICES = [
        ("in_stock", "In-stock Pet Sale"),
        ("preorder", "Pre-order Pet"),
    ]

    STATUS_CHOICES = [
        ("deposit", "Deposit / Waiting"),
        ("arrived", "Arrived"),
        ("completed", "Completed"),
        ("cancelled", "Customer Cancelled"),
        ("refunded", "Refunded"),
    ]

    PET_TYPE_CHOICES = [
        ("dog", "Dog"),
        ("cat", "Cat"),
        ("other", "Other"),
    ]

    sale_kind = models.CharField(
        max_length=30,
        choices=SALE_KIND_CHOICES,
        default="in_stock",
    )

    pet = models.ForeignKey(
        Pet,
        on_delete=models.PROTECT,
        related_name="sales",
        null=True,
        blank=True,
    )

    preorder_pet_type = models.CharField(
        max_length=20,
        choices=PET_TYPE_CHOICES,
        default="dog",
        blank=True,
    )
    preorder_breed = models.CharField(max_length=120, blank=True)
    preorder_gender = models.CharField(max_length=30, blank=True)
    deadline = models.DateField(null=True, blank=True)

    customer_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)

    sale_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    deposit_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    remaining_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    warranty_days = models.PositiveIntegerField(default=3)
    warranty_start_date = models.DateField(null=True, blank=True)
    warranty_expire_date = models.DateField(null=True, blank=True)

    sale_photo = models.ImageField(upload_to="pet_sales/", blank=True, null=True)

    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="deposit")
    note = models.TextField(blank=True)

    cancel_reason = models.TextField(blank=True)
    refund_reason = models.TextField(blank=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_pet_sales",
    )

    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def pet_type_display(self):
        if self.pet:
            return self.pet.get_pet_type_display()
        return dict(self.PET_TYPE_CHOICES).get(self.preorder_pet_type, "Pet")

    @property
    def breed_display(self):
        if self.pet:
            return self.pet.breed
        return self.preorder_breed

    @property
    def gender_display(self):
        if self.pet:
            return self.pet.gender
        return self.preorder_gender

    @property
    def pet_name_display(self):
        if self.pet and self.pet.name:
            return self.pet.name
        return ""

    @property
    def balance(self):
        return self.remaining_amount

    def set_warranty_dates(self):
        if not self.warranty_start_date:
            self.warranty_start_date = timezone.localdate()

        days = self.warranty_days or 3
        self.warranty_expire_date = self.warranty_start_date + timedelta(days=days)

    def build_copy_text(self):
        deadline_text = self.deadline.strftime("%d/%m/%Y") if self.deadline else "-"

        return (
            "🐶 BUBU PET PRE-ORDER\n"
            f"Breed: {self.breed_display or '-'}\n"
            f"Sex: {self.gender_display or '-'}\n"
            f"Remark: {self.note or '-'}\n"
            f"Full Price: ${self.sale_price}\n"
            f"Deposit: ${self.paid_amount}\n"
            f"Deadline: {deadline_text}\n\n"
            "Customer Info\n"
            f"Name: {self.customer_name}\n"
            f"Phone: {self.phone or '-'}\n"
            f"Location: {self.address or '-'}"
        )

    def save(self, *args, **kwargs):
        self.deposit_amount = self.paid_amount
        self.remaining_amount = self.sale_price - self.paid_amount

        if self.status not in ["cancelled", "refunded", "arrived"]:
            if self.sale_price > 0 and self.paid_amount >= self.sale_price:
                self.status = "completed"
            else:
                self.status = "deposit"

        if self.status == "completed":
            if not self.completed_at:
                self.completed_at = timezone.now()
            self.set_warranty_dates()

        super().save(*args, **kwargs)

        if self.pet:
            if self.status == "completed":
                self.pet.status = "sold"
                self.pet.save(update_fields=["status"])
            elif self.status == "deposit":
                self.pet.status = "reserved"
                self.pet.save(update_fields=["status"])
            elif self.status in ["cancelled", "refunded"]:
                self.pet.status = "in_stock"
                self.pet.save(update_fields=["status"])

    def __str__(self):
        return f"{self.customer_name} - {self.pet_type_display} - {self.breed_display}"


class PetWarrantyClaim(models.Model):
    sale = models.ForeignKey(
        PetSale,
        on_delete=models.CASCADE,
        related_name="warranty_claims",
    )

    problem_note = models.TextField()
    action_taken = models.TextField(blank=True)

    compensation_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    claim_photo = models.ImageField(upload_to="pet_claims/", blank=True, null=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_pet_warranty_claims",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Warranty Claim - {self.sale.customer_name}"