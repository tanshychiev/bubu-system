from django.contrib import admin

from .models import (
    StaffPayrollSetting,
    StaffShift,
    StaffWorkDay,
    BranchAttendanceQR,
    StaffAttendance,
    StaffPermissionRequest,
    StaffCommission,
    GroomingCommission,
    PayrollRecord,
    PayrollHistory,
)


@admin.register(StaffPayrollSetting)
class StaffPayrollSettingAdmin(admin.ModelAdmin):
    list_display = [
        "display_name",
        "branch",
        "base_salary",
        "start_work_date",
        "salary_cycle_start_day",
        "salary_open_after_days",
        "attendance_pin",
        "commission_enabled",
        "default_commission_rate",
        "pet_sale_commission_rate",
        "grooming_commission_rate",
        "allowed_day_off_per_month",
        "no_late_bonus",
        "is_active",
    ]
    list_filter = ["is_active", "commission_enabled", "staff__branch"]
    search_fields = [
        "staff__user__username",
        "staff__user__first_name",
        "staff__user__last_name",
    ]


@admin.register(StaffShift)
class StaffShiftAdmin(admin.ModelAdmin):
    list_display = ["staff", "name", "start_time", "end_time", "late_after_minutes", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["staff__user__username", "staff__user__first_name", "staff__user__last_name"]


@admin.register(StaffWorkDay)
class StaffWorkDayAdmin(admin.ModelAdmin):
    list_display = ["staff", "weekday", "is_work_day"]
    list_filter = ["weekday", "is_work_day"]
    search_fields = ["staff__user__username", "staff__user__first_name", "staff__user__last_name"]


@admin.register(BranchAttendanceQR)
class BranchAttendanceQRAdmin(admin.ModelAdmin):
    list_display = ["branch", "title", "token", "is_active", "created_at"]
    list_filter = ["branch", "is_active"]
    search_fields = ["branch__name", "title", "token"]


@admin.register(StaffAttendance)
class StaffAttendanceAdmin(admin.ModelAdmin):
    list_display = [
        "staff",
        "branch",
        "date",
        "status",
        "late_minutes",
        "check_in_time",
        "check_out_time",
        "distance_from_branch_meters",
        "is_suspicious",
        "scan_method",
    ]
    list_filter = ["branch", "status", "scan_method", "is_suspicious", "date"]
    search_fields = [
        "staff__user__username",
        "staff__user__first_name",
        "staff__user__last_name",
        "suspicious_reason",
    ]


@admin.register(StaffPermissionRequest)
class StaffPermissionRequestAdmin(admin.ModelAdmin):
    list_display = [
        "staff",
        "request_type",
        "date_from",
        "date_to",
        "status",
        "reviewed_by",
        "reviewed_at",
        "created_at",
    ]
    list_filter = ["request_type", "status", "date_from", "date_to"]
    search_fields = [
        "staff__user__username",
        "staff__user__first_name",
        "staff__user__last_name",
        "reason",
    ]


@admin.register(StaffCommission)
class StaffCommissionAdmin(admin.ModelAdmin):
    list_display = [
        "staff",
        "pet_sale",
        "sale_amount",
        "commission_rate",
        "commission_amount",
        "status",
        "payroll_record",
        "created_at",
    ]
    list_filter = ["status", "created_at"]
    search_fields = [
        "staff__user__username",
        "staff__user__first_name",
        "staff__user__last_name",
    ]


@admin.register(GroomingCommission)
class GroomingCommissionAdmin(admin.ModelAdmin):
    list_display = [
        "staff",
        "branch",
        "sale",
        "sale_amount",
        "commission_rate",
        "commission_amount",
        "status",
        "payroll_record",
        "created_at",
    ]
    list_filter = ["branch", "status", "created_at"]
    search_fields = [
        "staff__user__username",
        "staff__user__first_name",
        "staff__user__last_name",
        "sale__id",
    ]
    readonly_fields = ["commission_amount", "created_at"]


@admin.register(PayrollRecord)
class PayrollRecordAdmin(admin.ModelAdmin):
    date_hierarchy = "period_start"
    readonly_fields = ["net_salary", "created_at", "opened_at", "paid_at"]
    list_display = [
        "staff",
        "branch_name",
        "period_start",
        "period_end",
        "expected_open_date",
        "opened_at",
        "open_late_days",
        "base_salary",
        "pet_sale_commission",
        "grooming_commission",
        "total_commission",
        "dog_sale_count",
        "pet_sale_target_bonus",
        "attendance_bonus",
        "used_day_off",
        "over_day_off_days",
        "day_off_deduction",
        "late_days",
        "late_minutes",
        "absent_days",
        "permission_days",
        "net_salary",
        "status",
    ]
    list_filter = ["status", "period_start", "period_end"]
    search_fields = [
        "staff__user__username",
        "staff__user__first_name",
        "staff__user__last_name",
    ]


@admin.register(PayrollHistory)
class PayrollHistoryAdmin(admin.ModelAdmin):
    list_display = ["payroll", "action", "created_by", "created_at"]
    list_filter = ["action", "created_at"]
    search_fields = [
        "payroll__staff__user__username",
        "payroll__staff__user__first_name",
        "payroll__staff__user__last_name",
    ]
