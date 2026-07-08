from django.urls import path
from . import views

urlpatterns = [
    path("me/", views.staff_my_dashboard, name="staff_my_dashboard"),

    path("qr/", views.staff_qr_list, name="staff_qr_list"),
    path("qr/create/", views.staff_qr_create, name="staff_qr_create"),
    path("scan/<str:token>/", views.staff_scan_page, name="staff_scan_page"),
    path("scan/<str:token>/submit/", views.staff_scan_submit, name="staff_scan_submit"),

    path("settings/", views.staff_setting_list, name="staff_setting_list"),
    path("settings/create/", views.staff_setting_create, name="staff_setting_create"),
    path("settings/<int:staff_id>/edit/", views.staff_setting_edit, name="staff_setting_edit"),

    path("attendance/report/", views.staff_attendance_report, name="staff_attendance_report"),
    path("attendance/adjust/", views.staff_attendance_adjust, name="staff_attendance_adjust"),

    path("salary/", views.staff_salary_dashboard, name="staff_salary_dashboard"),
    path("salary/commissions/", views.staff_commission_list, name="staff_commission_list"),
    path("salary/open/<int:staff_id>/", views.staff_salary_open, name="staff_salary_open"),
    path("salary/payroll/<int:pk>/", views.payroll_record_detail, name="payroll_record_detail"),
    path("salary/payroll/<int:pk>/mark-paid/", views.payroll_mark_paid, name="payroll_mark_paid"),

    path("permission/create/", views.staff_permission_create, name="staff_permission_create"),

    path("branch-location/", views.branch_location_setting, name="branch_location_setting"),
]
