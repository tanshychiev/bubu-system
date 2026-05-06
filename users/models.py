from django.db import models
from django.contrib.auth.models import User

from inventory.models import Branch


class StaffProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="staff_profile",
    )

    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="staff_profiles",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Staff Profile"
        verbose_name_plural = "Staff Profiles"

    def __str__(self):
        if self.branch:
            return f"{self.user.username} - {self.branch.name}"
        return f"{self.user.username} - No Branch"