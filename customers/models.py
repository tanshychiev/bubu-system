from django.db import models
from django.contrib.auth.models import User


class Customer(models.Model):
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)

    # Old simple pet fields, keep for safety / old data
    pet_name = models.CharField(max_length=100, blank=True)
    pet_type = models.CharField(max_length=100, blank=True)

    points = models.IntegerField(default=0)
    total_spent = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_customers",
    )

    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_customers",
    )

    def __str__(self):
        return self.name


class CustomerPet(models.Model):
    SOURCE_CHOICES = [
        ("bubu_sale", "Bought at BUBU"),
        ("bubu_preorder", "BUBU Pre-order"),
        ("customer_own", "Customer Own Pet"),
    ]

    PET_TYPE_CHOICES = [
        ("dog", "Dog"),
        ("cat", "Cat"),
        ("other", "Other"),
    ]

    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="pets",
    )

    photo = models.ImageField(
        upload_to="customer_pets/",
        blank=True,
        null=True,
    )

    pet_name = models.CharField(max_length=120, blank=True)
    pet_type = models.CharField(max_length=20, choices=PET_TYPE_CHOICES, default="dog")
    breed = models.CharField(max_length=120, blank=True)
    gender = models.CharField(max_length=30, blank=True)
    color = models.CharField(max_length=80, blank=True)

    birth_date = models.DateField(null=True, blank=True)
    age_text = models.CharField(max_length=80, blank=True)

    source = models.CharField(
        max_length=30,
        choices=SOURCE_CHOICES,
        default="customer_own",
    )

    bought_date = models.DateField(null=True, blank=True)

    # Link to pet sale later
    pet_sale = models.ForeignKey(
        "pets.PetSale",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customer_pet_profiles",
    )

    warranty_start_date = models.DateField(null=True, blank=True)
    warranty_expire_date = models.DateField(null=True, blank=True)

    note = models.TextField(blank=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_customer_pets",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def source_badge(self):
        if self.source == "bubu_sale":
            return "Bought at BUBU"
        if self.source == "bubu_preorder":
            return "BUBU Pre-order"
        return "Customer Own Pet"

    def __str__(self):
        name = self.pet_name or self.breed or self.get_pet_type_display()
        return f"{self.customer.name} - {name}"


class CustomerHistory(models.Model):
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="histories",
    )

    field_name = models.CharField(max_length=50)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)

    changed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    changed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.customer.name} - {self.field_name}"