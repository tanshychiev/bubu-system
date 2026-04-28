from django.db import models
from django.contrib.auth.models import User


class DeliveryOrder(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("OUT_FOR_DELIVERY", "Out for Delivery"),
        ("DELIVERED", "Delivered"),
        ("CANCELLED", "Cancelled"),
    ]

    customer_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=50)
    address = models.TextField()

    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default="PENDING")

    note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.customer_name


class DeliveryStatusLog(models.Model):
    delivery = models.ForeignKey(
        DeliveryOrder,
        on_delete=models.CASCADE,
        related_name="logs"
    )

    old_status = models.CharField(max_length=50)
    new_status = models.CharField(max_length=50)

    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.delivery} {self.old_status} → {self.new_status}"