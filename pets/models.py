from datetime import timedelta

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

from inventory.models import Branch


class PetBreed(models.Model):
    TYPE_CHOICES = [
        ("dog", "Dog"),
        ("cat", "Cat"),
        ("other", "Other"),
    ]

    pet_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default="dog")
    name = models.CharField(max_length=120)

    # Breed sample/reference photo
    photo = models.ImageField(upload_to="pet_breeds/", blank=True, null=True)

    default_cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    default_sale_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    color_options = models.CharField(
        max_length=255,
        blank=True,
        help_text="Example: White, Cream, Brown, Black",
    )

    sex_options = models.CharField(
        max_length=255,
        blank=True,
        default="Male,Female",
        help_text="Example: Male, Female",
    )

    special_type_options = models.CharField(
        max_length=255,
        blank=True,
        help_text="Example: Teacup, Mini, Standard, Show Grade",
    )

    note = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_pet_breeds",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["pet_type", "name"]

    def __str__(self):
        return f"{self.get_pet_type_display()} - {self.name}"


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

    branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pets",
        help_text="Which branch/shop this pet is currently stocked in.",
    )

    breed_profile = models.ForeignKey(
        PetBreed,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pets",
    )

    pet_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default="dog")

    # Keep old breed field for safety / old data
    breed = models.CharField(max_length=120, blank=True)

    name = models.CharField(max_length=120, blank=True)
    gender = models.CharField(max_length=30, blank=True)
    color = models.CharField(max_length=80, blank=True)
    special_type = models.CharField(max_length=120, blank=True)

    age_months_at_stock_in = models.PositiveIntegerField(
        default=0,
        help_text="Age in months when this pet was stocked in.",
    )

    age_recorded_date = models.DateField(
        default=timezone.localdate,
        help_text="Date when age was recorded.",
    )

    death_date = models.DateField(null=True, blank=True)

    # Actual real pet photo when stock-in
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
    def branch_name(self):
        if self.branch:
            return self.branch.name
        return "No Branch"

    @property
    def breed_name(self):
        if self.breed_profile:
            return self.breed_profile.name
        return self.breed

    @property
    def display_photo(self):
        if self.photo:
            return self.photo
        if self.breed_profile and self.breed_profile.photo:
            return self.breed_profile.photo
        return None

    @property
    def current_age_months(self):
        base_months = int(self.age_months_at_stock_in or 0)

        if not self.age_recorded_date:
            return base_months

        today = timezone.localdate()

        months_passed = (
            (today.year - self.age_recorded_date.year) * 12
            + (today.month - self.age_recorded_date.month)
        )

        if today.day < self.age_recorded_date.day:
            months_passed -= 1

        if months_passed < 0:
            months_passed = 0

        return base_months + months_passed

    @property
    def current_age_display(self):
        months = self.current_age_months

        if months <= 0:
            return "-"

        if months < 12:
            return f"{months} month" if months == 1 else f"{months} months"

        years = months // 12
        remain_months = months % 12

        if remain_months == 0:
            return f"{years} year" if years == 1 else f"{years} years"

        year_text = f"{years} year" if years == 1 else f"{years} years"
        month_text = (
            f"{remain_months} month"
            if remain_months == 1
            else f"{remain_months} months"
        )

        return f"{year_text} {month_text}"

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

    def save(self, *args, **kwargs):
        if self.breed_profile:
            self.pet_type = self.breed_profile.pet_type

            if not self.breed:
                self.breed = self.breed_profile.name

            if not self.cost_price:
                self.cost_price = self.breed_profile.default_cost_price

            if not self.sale_price:
                self.sale_price = self.breed_profile.default_sale_price

        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.branch_name} - "
            f"{self.get_pet_type_display()} - "
            f"{self.breed_name} - "
            f"{self.get_status_display()}"
        )


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
    preorder_color = models.CharField(max_length=80, blank=True)
    preorder_special_type = models.CharField(max_length=120, blank=True)

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

    # Old single photo field kept for old data / fallback
    sale_photo = models.ImageField(upload_to="pet_sales/", blank=True, null=True)

    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="deposit")
    note = models.TextField(blank=True)

    cancel_reason = models.TextField(blank=True)
    refund_reason = models.TextField(blank=True)

    # User who recorded the sale in the system
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_pet_sales",
    )

    # Real seller/staff who sold the pet
    seller = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pet_sales_as_seller",
        help_text="Real seller/staff who sold this pet.",
    )

    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def seller_display(self):
        if self.seller:
            return self.seller.get_full_name() or self.seller.username

        if self.created_by:
            return self.created_by.get_full_name() or self.created_by.username

        return "-"

    @property
    def branch_display(self):
        if self.pet and self.pet.branch:
            return self.pet.branch.name
        return "No Branch"

    @property
    def pet_type_display(self):
        if self.pet:
            return self.pet.get_pet_type_display()
        return dict(self.PET_TYPE_CHOICES).get(self.preorder_pet_type, "Pet")

    @property
    def breed_display(self):
        if self.pet:
            return self.pet.breed_name
        return self.preorder_breed

    @property
    def gender_display(self):
        if self.pet:
            return self.pet.gender
        return self.preorder_gender

    @property
    def color_display(self):
        if self.pet:
            return self.pet.color
        return self.preorder_color

    @property
    def special_type_display(self):
        if self.pet:
            return self.pet.special_type
        return self.preorder_special_type

    @property
    def pet_name_display(self):
        if self.pet and self.pet.name:
            return self.pet.name
        return ""

    @property
    def age_display(self):
        if self.pet:
            return self.pet.current_age_display
        return "-"

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
            f"Branch: {self.branch_display}\n"
            f"Breed: {self.breed_display or '-'}\n"
            f"Sex: {self.gender_display or '-'}\n"
            f"Color: {self.color_display or '-'}\n"
            f"Special Type: {self.special_type_display or '-'}\n"
            f"Remark: {self.note or '-'}\n"
            f"Full Price: ${self.sale_price}\n"
            f"Deposit: ${self.paid_amount}\n"
            f"Deadline: {deadline_text}\n\n"
            "Customer Info\n"
            f"Name: {self.customer_name}\n"
            f"Phone: {self.phone or '-'}\n"
            f"Location: {self.address or '-'}\n"
            f"Seller: {self.seller_display}"
        )

    def save(self, *args, **kwargs):
        self.deposit_amount = self.paid_amount
        self.remaining_amount = self.sale_price - self.paid_amount

        # Important:
        # If status is already completed by view button, keep it completed.
        # Do not change completed back to deposit, even if sale price is $0.
        if self.status == "completed":
            if not self.completed_at:
                self.completed_at = timezone.now()
            self.set_warranty_dates()

        elif self.status in ["cancelled", "refunded", "arrived"]:
            pass

        else:
            if self.sale_price > 0 and self.paid_amount >= self.sale_price:
                self.status = "completed"

                if not self.completed_at:
                    self.completed_at = timezone.now()

                self.set_warranty_dates()
            else:
                self.status = "deposit"

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


class PetSalePhoto(models.Model):
    sale = models.ForeignKey(
        PetSale,
        on_delete=models.CASCADE,
        related_name="photos",
    )

    photo = models.ImageField(upload_to="pet_sale_photos/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"Photo for sale #{self.sale_id}"


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