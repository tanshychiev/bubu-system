# Add these models at the END of staffs/models.py

class GroomingWorkType(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.SlugField(max_length=60, unique=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class POSServiceWorkMapping(models.Model):
    item = models.ForeignKey(
        "inventory.Item",
        on_delete=models.CASCADE,
        related_name="grooming_work_mappings",
    )
    work_type = models.ForeignKey(
        GroomingWorkType,
        on_delete=models.CASCADE,
        related_name="pos_mappings",
    )
    quantity = models.DecimalField(max_digits=8, decimal_places=2, default=1)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["item", "work_type"],
                name="unique_pos_item_work_type_mapping",
            )
        ]
        ordering = ["item__name", "work_type__sort_order", "work_type__name"]

    def __str__(self):
        return f"{self.item} → {self.work_type} × {self.quantity}"


class GroomingWorkRecord(models.Model):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("confirmed", "Confirmed"),
        ("rejected", "Rejected"),
        ("locked", "Locked in Payroll"),
    ]

    staff = models.ForeignKey(
        StaffProfile,
        on_delete=models.CASCADE,
        related_name="grooming_work_records",
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="grooming_work_records",
    )
    work_type = models.ForeignKey(
        GroomingWorkType,
        on_delete=models.PROTECT,
        related_name="work_records",
    )
    work_date = models.DateField(default=timezone.localdate)
    quantity = models.DecimalField(max_digits=8, decimal_places=2, default=1)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_grooming_work_records",
    )
    confirmed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="confirmed_grooming_work_records",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    payroll_record = models.ForeignKey(
        "PayrollRecord",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="grooming_work_records",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-work_date", "-created_at"]
        indexes = [
            models.Index(fields=["work_date", "branch", "status"]),
            models.Index(fields=["staff", "work_date"]),
        ]

    @property
    def staff_name(self):
        return self.staff.user.get_full_name() or self.staff.user.username

    def __str__(self):
        return f"{self.staff_name} - {self.work_type} × {self.quantity} - {self.work_date}"


class GroomingHelperWork(models.Model):
    """Admin-only quantity for helpers who do not receive commission."""
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="grooming_helper_work",
    )
    work_type = models.ForeignKey(
        GroomingWorkType,
        on_delete=models.PROTECT,
        related_name="helper_records",
    )
    work_date = models.DateField(default=timezone.localdate)
    helper_name = models.CharField(max_length=100, default="Helper")
    quantity = models.DecimalField(max_digits=8, decimal_places=2, default=1)
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_grooming_helper_work",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-work_date", "work_type__sort_order"]

    def __str__(self):
        return f"{self.helper_name} - {self.work_type} × {self.quantity}"


class StaffWorkCommissionRule(models.Model):
    CALCULATION_CHOICES = [
        ("per_unit", "Every unit × rate"),
        ("after_threshold", "Only units after threshold × rate"),
        ("fixed_target", "Reach target = fixed bonus"),
        ("per_block", "Every completed block = fixed amount"),
    ]

    staff = models.ForeignKey(
        StaffProfile,
        on_delete=models.CASCADE,
        related_name="work_commission_rules",
    )
    work_type = models.ForeignKey(
        GroomingWorkType,
        on_delete=models.CASCADE,
        related_name="staff_commission_rules",
    )
    calculation_type = models.CharField(
        max_length=30,
        choices=CALCULATION_CHOICES,
        default="after_threshold",
    )
    threshold_quantity = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    rate_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    block_quantity = models.DecimalField(max_digits=8, decimal_places=2, default=1)
    effective_from = models.DateField(default=timezone.localdate)
    effective_to = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["staff__user__username", "work_type__sort_order", "-effective_from"]

    def calculate(self, quantity):
        quantity = Decimal(quantity or 0)
        threshold = Decimal(self.threshold_quantity or 0)
        rate = Decimal(self.rate_amount or 0)
        block = Decimal(self.block_quantity or 1)

        if self.calculation_type == "per_unit":
            return quantity * rate
        if self.calculation_type == "after_threshold":
            return max(quantity - threshold, Decimal("0")) * rate
        if self.calculation_type == "fixed_target":
            return rate if quantity >= threshold else Decimal("0")
        if self.calculation_type == "per_block":
            if block <= 0:
                return Decimal("0")
            return Decimal(int(quantity // block)) * rate
        return Decimal("0")

    def __str__(self):
        return f"{self.staff} - {self.work_type} - {self.get_calculation_type_display()}"


class PayrollAdjustment(models.Model):
    TYPE_CHOICES = [("bonus", "Bonus"), ("deduction", "Deduction"), ("advance", "Salary Advance")]
    staff = models.ForeignKey(
        StaffProfile,
        on_delete=models.CASCADE,
        related_name="payroll_adjustments",
    )
    adjustment_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    record_date = models.DateField(default=timezone.localdate)
    reason = models.CharField(max_length=200)
    note = models.TextField(blank=True)
    payroll_record = models.ForeignKey(
        "PayrollRecord",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="adjustments",
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_payroll_adjustments",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-record_date", "-created_at"]

    def __str__(self):
        return f"{self.staff} - {self.get_adjustment_type_display()} ${self.amount}"
