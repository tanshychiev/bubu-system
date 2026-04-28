from django.db import models
from django.contrib.auth.models import User


class Customer(models.Model):
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)
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
    
class CustomerHistory(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="histories")

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