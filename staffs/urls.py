from django.urls import path

from . import views, work_views


urlpatterns = [
    # ==================================================
    # STAFF DASHBOARD
    # ==================================================
    path(
        "me/",
        views.staff_my_dashboard,
        name="staff_my_dashboard",
    ),

    # ==================================================
    # ATTENDANCE QR
    # ==================================================
    path(
        "qr/",
        views.staff_qr_list,
        name="staff_qr_list",
    ),
    path(
        "qr/create/",
        views.staff_qr_create,
        name="staff_qr_create",
    ),
    path(
        "scan/<str:token>/",
        views.staff_scan_page,
        name="staff_scan_page",
    ),
    path(
        "scan/<str:token>/submit/",
        views.staff_scan_submit,
        name="staff_scan_submit",
    ),

    # ==================================================
    # STAFF PAYROLL SETTINGS
    # ==================================================
    path(
        "settings/",
        views.staff_setting_list,
        name="staff_setting_list",
    ),
    path(
        "settings/create/",
        views.staff_setting_create,
        name="staff_setting_create",
    ),
    path(
        "settings/<int:staff_id>/edit/",
        views.staff_setting_edit,
        name="staff_setting_edit",
    ),

    # ==================================================
    # ATTENDANCE
    # ==================================================
    path(
        "attendance/report/",
        views.staff_attendance_report,
        name="staff_attendance_report",
    ),
    path(
        "attendance/adjust/",
        views.staff_attendance_adjust,
        name="staff_attendance_adjust",
    ),

    # ==================================================
    # GROOMING WORK — STAFF
    # ==================================================
    path(
        "work/my/",
        work_views.grooming_my_work,
        name="grooming_my_work",
    ),
    path(
        "work/<int:pk>/delete/",
        work_views.grooming_work_delete,
        name="grooming_work_delete",
    ),

    # ==================================================
    # GROOMING WORK — ADMIN COMPARISON
    # ==================================================
    path(
        "work/comparison/",
        work_views.grooming_daily_comparison,
        name="grooming_daily_comparison",
    ),
    path(
        "work/comparison/helper/add/",
        work_views.grooming_helper_add,
        name="grooming_helper_add",
    ),
    path(
        "work/comparison/confirm/",
        work_views.grooming_confirm_day,
        name="grooming_confirm_day",
    ),

    # ==================================================
    # GROOMING WORK SETTINGS
    # ==================================================
    path(
        "work/settings/",
        work_views.grooming_work_settings,
        name="grooming_work_settings",
    ),
    path(
        "work/commission-rules/",
        work_views.staff_work_commission_rules,
        name="staff_work_commission_rules",
    ),

    # ==================================================
    # SALARY AND COMMISSION
    # ==================================================
    path(
        "salary/",
        views.staff_salary_dashboard,
        name="staff_salary_dashboard",
    ),
    path(
        "salary/commissions/",
        views.staff_commission_list,
        name="staff_commission_list",
    ),
    path(
        "salary/adjustments/",
        work_views.payroll_adjustment_list,
        name="payroll_adjustment_list",
    ),
    path(
        "salary/open/<int:staff_id>/",
        views.staff_salary_open,
        name="staff_salary_open",
    ),
    path(
        "salary/payroll/<int:pk>/",
        views.payroll_record_detail,
        name="payroll_record_detail",
    ),
    path(
        "salary/payroll/<int:pk>/mark-paid/",
        views.payroll_mark_paid,
        name="payroll_mark_paid",
    ),

    # ==================================================
    # STAFF PERMISSION
    # ==================================================
    path(
        "permission/create/",
        views.staff_permission_create,
        name="staff_permission_create",
    ),

    # ==================================================
    # BRANCH LOCATION
    # ==================================================
    path(
        "branch-location/",
        views.branch_location_setting,
        name="branch_location_setting",
    ),
]