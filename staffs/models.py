from decimal import Decimal
import secrets

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

from users.models import StaffProfile
from inventory.models import Branch


class StaffPayrollSetting(models.Model):
    staff = models.OneToOneField(
        StaffProfile,
        on_delete=models.CASCADE,
        related_name="payroll_setting",
    )

    base_salary = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    start_work_date = models.DateField(default=timezone.localdate)

    salary_cycle_start_day = models.PositiveIntegerField(
        default=1,
        help_text="Example: 5 means salary cycle is 5th this month to 4th next month.",
    )

    salary_open_after_days = models.PositiveIntegerField(
        default=6,
        help_text="Example: period ends on 4th, open after 6 days = 10th.",
    )

    attendance_pin = models.CharField(
        max_length=20,
        blank=True,
        help_text="PIN staff enters after scanning branch QR.",
    )

    commission_enabled = models.BooleanField(default=True)

    default_commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=5,
        help_text="Example: 5 means 5%.",
    )

    late_deduction_per_day = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    absent_deduction_per_day = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # Salary attendance rule
    allowed_day_off_per_month = models.PositiveIntegerField(default=3)
    unused_day_off_bonus_per_day = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    over_day_off_deduction_per_day = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    no_late_bonus = models.DecimalField(max_digits=10, decimal_places=2, default=10)
    allowed_late_times = models.PositiveIntegerField(default=3)

    # Commission rules
    pet_sale_commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=5,
        help_text="Pet sale commission percentage. Example: 5 means 5%.",
    )
    grooming_commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=5,
        help_text="Grooming commission percentage. Example: 5 means 5%.",
    )

    is_active = models.BooleanField(default=True)
    note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def display_name(self):
        return self.staff.user.get_full_name() or self.staff.user.username

    @property
    def branch(self):
        return getattr(self.staff, "branch", None)

    def __str__(self):
        branch_name = self.branch.name if self.branch else "No Branch"
        return f"{self.display_name} - {branch_name} - ${self.base_salary}"


class StaffShift(models.Model):
    staff = models.ForeignKey(
        StaffProfile,
        on_delete=models.CASCADE,
        related_name="payroll_shifts",
    )

    name = models.CharField(max_length=100, default="Default Shift")

    start_time = models.TimeField()
    end_time = models.TimeField()

    late_after_minutes = models.PositiveIntegerField(
        default=10,
        help_text="Example: shift starts 8:00, late after 10 minutes means late from 8:11.",
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["staff__user__username", "start_time"]

    def __str__(self):
        staff_name = self.staff.user.get_full_name() or self.staff.user.username
        return f"{staff_name} - {self.name}"


class StaffWorkDay(models.Model):
    WEEKDAY_CHOICES = [
        (0, "Monday"),
        (1, "Tuesday"),
        (2, "Wednesday"),
        (3, "Thursday"),
        (4, "Friday"),
        (5, "Saturday"),
        (6, "Sunday"),
    ]

    staff = models.ForeignKey(
        StaffProfile,
        on_delete=models.CASCADE,
        related_name="work_days",
    )

    weekday = models.PositiveSmallIntegerField(choices=WEEKDAY_CHOICES)
    is_work_day = models.BooleanField(default=True)

    class Meta:
        unique_together = ("staff", "weekday")
        ordering = ["staff__user__username", "weekday"]

    def __str__(self):
        return f"{self.staff} - {self.get_weekday_display()}"


class BranchAttendanceQR(models.Model):
    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="attendance_qrs",
    )

    token = models.CharField(max_length=120, unique=True, blank=True)
    title = models.CharField(max_length=120, default="Main Attendance QR")

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(40)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.branch.name} - {self.title}"


class StaffAttendance(models.Model):
    STATUS_CHOICES = [
        ("present", "Present"),
        ("late", "Late"),
        ("absent", "Absent"),
        ("leave", "Leave"),
        ("permission", "Permission"),
        ("half_day", "Half Day"),
    ]

    SCAN_METHOD_CHOICES = [
        ("branch_qr", "Branch QR"),
        ("manual", "Manual"),
    ]

    staff = models.ForeignKey(
        StaffProfile,
        on_delete=models.CASCADE,
        related_name="payroll_attendances",
    )

    branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payroll_attendances",
    )

    shift = models.ForeignKey(
        StaffShift,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendances",
    )

    date = models.DateField(default=timezone.localdate)

    check_in_time = models.DateTimeField(null=True, blank=True)
    check_out_time = models.DateTimeField(null=True, blank=True)

    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="present")
    late_minutes = models.PositiveIntegerField(default=0)

    scan_method = models.CharField(
        max_length=30,
        choices=SCAN_METHOD_CHOICES,
        default="branch_qr",
    )

    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    location_accuracy = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    distance_from_branch_meters = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    device_info = models.TextField(blank=True)
    ip_address = models.CharField(max_length=80, blank=True)

    is_suspicious = models.BooleanField(default=False)
    suspicious_reason = models.TextField(blank=True)

    note = models.TextField(blank=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_staff_attendances",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("staff", "date")
        ordering = ["-date", "staff__user__username"]

    @property
    def staff_name(self):
        return self.staff.user.get_full_name() or self.staff.user.username

    def save(self, *args, **kwargs):
        if not self.branch and self.staff and getattr(self.staff, "branch", None):
            self.branch = self.staff.branch

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.staff_name} - {self.date} - {self.get_status_display()}"


class StaffPermissionRequest(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("cancelled", "Cancelled"),
    ]

    REQUEST_TYPE_CHOICES = [
        ("late", "Come Late"),
        ("leave_early", "Leave Early"),
        ("day_leave", "Day Leave"),
        ("sick_leave", "Sick Leave"),
        ("other", "Other"),
    ]

    staff = models.ForeignKey(
        StaffProfile,
        on_delete=models.CASCADE,
        related_name="permission_requests",
    )

    request_type = models.CharField(max_length=30, choices=REQUEST_TYPE_CHOICES, default="other")

    date_from = models.DateField()
    date_to = models.DateField()

    time_from = models.TimeField(null=True, blank=True)
    time_to = models.TimeField(null=True, blank=True)

    reason = models.TextField()
    proof_photo = models.ImageField(upload_to="staff_permissions/", blank=True, null=True)

    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="pending")

    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_staff_permissions",
    )

    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def staff_name(self):
        return self.staff.user.get_full_name() or self.staff.user.username

    def __str__(self):
        return f"{self.staff_name} - {self.get_request_type_display()} - {self.get_status_display()}"


class StaffCommission(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("paid", "Paid"),
        ("cancelled", "Cancelled"),
    ]

    staff = models.ForeignKey(
        StaffProfile,
        on_delete=models.CASCADE,
        related_name="pet_sale_commissions",
    )

    pet_sale = models.OneToOneField(
        "pets.PetSale",
        on_delete=models.CASCADE,
        related_name="staff_commission",
    )

    sale_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2, default=5)
    commission_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="pending")

    payroll_record = models.ForeignKey(
        "PayrollRecord",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="commissions",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def staff_name(self):
        return self.staff.user.get_full_name() or self.staff.user.username

    def save(self, *args, **kwargs):
        self.commission_amount = (
            Decimal(self.sale_amount or 0)
            * Decimal(self.commission_rate or 0)
            / Decimal("100")
        )
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.staff_name} - Pet Sale #{self.pet_sale_id} - ${self.commission_amount}"


class GroomingCommission(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("paid", "Paid"),
        ("cancelled", "Cancelled"),
    ]

    staff = models.ForeignKey(
        StaffProfile,
        on_delete=models.CASCADE,
        related_name="grooming_commissions",
    )

    branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="grooming_commissions",
    )

    sale = models.OneToOneField(
        "pos.Sale",
        on_delete=models.CASCADE,
        related_name="grooming_commission",
    )

    sale_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=5,
        help_text="Example: 5 means 5% of grooming sale amount.",
    )
    commission_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="approved")

    payroll_record = models.ForeignKey(
        "PayrollRecord",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="grooming_commissions",
    )

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_grooming_commissions",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def staff_name(self):
        return self.staff.user.get_full_name() or self.staff.user.username

    def save(self, *args, **kwargs):
        self.commission_amount = (
            Decimal(self.sale_amount or 0)
            * Decimal(self.commission_rate or 0)
            / Decimal("100")
        )
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.staff_name} - POS Sale #{self.sale_id} - ${self.commission_amount}"


class PayrollRecord(models.Model):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("opened", "Opened"),
        ("paid", "Paid"),
        ("cancelled", "Cancelled"),
    ]

    staff = models.ForeignKey(
        StaffProfile,
        on_delete=models.CASCADE,
        related_name="payroll_records",
    )

    period_start = models.DateField()
    period_end = models.DateField()
    expected_open_date = models.DateField()

    opened_at = models.DateTimeField(null=True, blank=True)

    opened_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="opened_payroll_records",
    )

    base_salary = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    pet_sale_commission = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    grooming_commission = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_commission = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    dog_sale_count = models.PositiveIntegerField(default=0)
    pet_sale_target_bonus = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    allowed_day_off = models.PositiveIntegerField(default=3)
    used_day_off = models.PositiveIntegerField(default=0)
    over_day_off_days = models.PositiveIntegerField(default=0)
    unused_day_off_days = models.PositiveIntegerField(default=0)

    attendance_bonus = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    unused_day_off_bonus = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    day_off_deduction = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    late_days = models.PositiveIntegerField(default=0)
    late_minutes = models.PositiveIntegerField(default=0)
    absent_days = models.PositiveIntegerField(default=0)
    permission_days = models.PositiveIntegerField(default=0)

    late_deduction = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    absent_deduction = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    bonus = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    other_deduction = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    net_salary = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="draft")

    paid_at = models.DateTimeField(null=True, blank=True)

    paid_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="paid_payroll_records",
    )

    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-period_start", "staff__user__username"]

    @property
    def staff_name(self):
        return self.staff.user.get_full_name() or self.staff.user.username

    @property
    def branch_name(self):
        if getattr(self.staff, "branch", None):
            return self.staff.branch.name
        return "No Branch"

    @property
    def open_late_days(self):
        if not self.opened_at:
            return 0

        opened_date = self.opened_at.date()

        if opened_date <= self.expected_open_date:
            return 0

        return (opened_date - self.expected_open_date).days

    def calculate_net_salary(self):
        self.net_salary = (
            Decimal(self.base_salary or 0)
            + Decimal(self.total_commission or 0)
            + Decimal(self.attendance_bonus or 0)
            + Decimal(self.unused_day_off_bonus or 0)
            + Decimal(self.pet_sale_target_bonus or 0)
            + Decimal(self.bonus or 0)
            - Decimal(self.day_off_deduction or 0)
            - Decimal(self.late_deduction or 0)
            - Decimal(self.absent_deduction or 0)
            - Decimal(self.other_deduction or 0)
        )

    def save(self, *args, **kwargs):
        self.calculate_net_salary()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.staff_name} - {self.period_start} to {self.period_end}"


class PayrollHistory(models.Model):
    ACTION_CHOICES = [
        ("created", "Created"),
        ("opened", "Opened"),
        ("edited", "Edited"),
        ("paid", "Paid"),
        ("cancelled", "Cancelled"),
        ("commission_added", "Commission Added"),
        ("deduction_added", "Deduction Added"),
        ("permission_requested", "Permission Requested"),
        ("permission_approved", "Permission Approved"),
        ("permission_rejected", "Permission Rejected"),
    ]

    payroll = models.ForeignKey(
        PayrollRecord,
        on_delete=models.CASCADE,
        related_name="histories",
    )

    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    note = models.TextField(blank=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_payroll_histories",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.payroll} - {self.get_action_display()}"
    
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
