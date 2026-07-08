import base64
import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from math import atan2, cos, radians, sin, sqrt

import qrcode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.sites.shortcuts import get_current_site
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time

from inventory.models import Branch
from pets.models import PetSale
from users.models import StaffProfile

from staffs.telegram import send_staff_telegram_message

from .models import (
    BranchAttendanceQR,
    GroomingCommission,
    PayrollHistory,
    PayrollRecord,
    StaffAttendance,
    StaffCommission,
    StaffPayrollSetting,
    StaffPermissionRequest,
    StaffShift,
)


# =========================================================
# SMALL HELPERS
# =========================================================

def _staff_name(staff):
    return staff.user.get_full_name() or staff.user.username


def _staff_position(staff):
    try:
        if hasattr(staff, "get_role_display"):
            role_display = staff.get_role_display()
            if role_display:
                return role_display
    except Exception:
        pass

    role = getattr(staff, "role", "") or "-"
    return str(role).replace("_", " ").title()


def _format_minutes(minutes):
    try:
        minutes = int(minutes or 0)
    except Exception:
        minutes = 0

    if minutes <= 0:
        return "0m"

    hours = minutes // 60
    mins = minutes % 60

    if hours and mins:
        return f"{hours}h{mins}m"

    if hours:
        return f"{hours}h"

    return f"{mins}m"


def _get_ip_address(request):
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")

    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()

    return request.META.get("REMOTE_ADDR", "")


def _make_qr_base64(text):
    qr = qrcode.QRCode(
        version=1,
        box_size=10,
        border=4,
    )
    qr.add_data(text)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    buffer = BytesIO()
    img.save(buffer, format="PNG")

    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def _distance_meters(lat1, lon1, lat2, lon2):
    earth_radius = 6371000

    dlat = radians(float(lat2) - float(lat1))
    dlon = radians(float(lon2) - float(lon1))

    a = (
        sin(dlat / 2) ** 2
        + cos(radians(float(lat1)))
        * cos(radians(float(lat2)))
        * sin(dlon / 2) ** 2
    )

    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return earth_radius * c


def _get_staff_profile_from_user(user):
    try:
        return user.staff_profile
    except Exception:
        return None


def _get_active_shift(staff):
    return (
        StaffShift.objects
        .filter(staff=staff, is_active=True)
        .order_by("start_time")
        .first()
    )


def _check_arrival_status(today, now, shift):
    """
    Returns:
    status, minutes_value, status_text, status_icon

    Examples:
    present, 3, Early 3m, 🟢
    late, 926, Late 15h26m, 🔴
    present, 0, On time, 🟢
    """
    if not shift:
        return "present", 0, "On time", "🟢"

    shift_start = timezone.make_aware(
        datetime.combine(today, shift.start_time),
        timezone.get_current_timezone(),
    )

    allowed_time = shift_start + timezone.timedelta(
        minutes=shift.late_after_minutes or 0,
    )

    if now < shift_start:
        early_minutes = int((shift_start - now).total_seconds() // 60)
        return "present", early_minutes, f"Early {_format_minutes(early_minutes)}", "🟢"

    if now > allowed_time:
        late_minutes = int((now - allowed_time).total_seconds() // 60)
        return "late", late_minutes, f"Late {_format_minutes(late_minutes)}", "🔴"

    return "present", 0, "On time", "🟢"


def _check_location(branch, latitude, longitude):
    """
    Returns:
    distance, location_status, is_suspicious, suspicious_reason
    """
    if not latitude or not longitude:
        return None, "No GPS", True, "Staff did not allow GPS location."

    if not getattr(branch, "latitude", None) or not getattr(branch, "longitude", None):
        return None, "No branch GPS setting", True, "Branch GPS location is not set."

    distance = Decimal(str(round(_distance_meters(
        branch.latitude,
        branch.longitude,
        latitude,
        longitude,
    ), 2)))

    allowed_radius = getattr(branch, "allowed_radius_meters", None) or 150

    if distance > allowed_radius:
        return (
            distance,
            "Outside branch",
            True,
            f"Outside allowed radius. Distance {distance}m, allowed {allowed_radius}m.",
        )

    return distance, "Near branch", False, ""


# =========================================================
# QR LIST / QR CREATE
# =========================================================

@login_required
def staff_qr_list(request):
    qr_codes = (
        BranchAttendanceQR.objects
        .select_related("branch")
        .filter(is_active=True)
        .order_by("branch__name", "title")
    )

    current_site = get_current_site(request)
    protocol = "https" if request.is_secure() else "http"

    qr_items = []

    for qr in qr_codes:
        scan_path = reverse("staff_scan_page", args=[qr.token])
        scan_url = f"{protocol}://{current_site.domain}{scan_path}"

        qr_items.append({
            "qr": qr,
            "scan_url": scan_url,
            "qr_base64": _make_qr_base64(scan_url),
        })

    return render(request, "staffs/staff_qr_list.html", {
        "qr_items": qr_items,
    })


@login_required
def staff_qr_create(request):
    if not request.user.has_perm("auth.view_user"):
        messages.error(request, "You do not have permission to create attendance QR.")
        return redirect("staff_my_dashboard")

    branches = Branch.objects.filter(is_active=True).order_by("name")

    if request.method == "POST":
        branch_id = request.POST.get("branch")
        title = request.POST.get("title", "").strip() or "Main Attendance QR"

        branch = get_object_or_404(Branch, id=branch_id, is_active=True)

        BranchAttendanceQR.objects.create(
            branch=branch,
            title=title,
            is_active=True,
        )

        messages.success(request, f"Attendance QR created for {branch.name}.")
        return redirect("staff_qr_list")

    return render(request, "staffs/staff_qr_form.html", {
        "branches": branches,
    })


# =========================================================
# STAFF SCAN
# =========================================================

def staff_scan_page(request, token):
    qr = get_object_or_404(
        BranchAttendanceQR.objects.select_related("branch"),
        token=token,
        is_active=True,
    )

    staffs = (
        StaffProfile.objects
        .select_related("user", "branch")
        .filter(branch=qr.branch, user__is_active=True)
        .order_by("user__first_name", "user__username")
    )

    return render(request, "staffs/staff_scan_page.html", {
        "qr": qr,
        "staffs": staffs,
        "today": timezone.localdate(),
    })


def staff_scan_submit(request, token):
    qr = get_object_or_404(
        BranchAttendanceQR.objects.select_related("branch"),
        token=token,
        is_active=True,
    )

    if request.method != "POST":
        return redirect("staff_scan_page", token=qr.token)

    staff_id = request.POST.get("staff_id", "").strip()

    if not staff_id:
        messages.error(request, "Please select your staff name first.")
        return redirect("staff_scan_page", token=qr.token)

    pin = request.POST.get("pin", "").strip()
    action = request.POST.get("action", "check_in")
    late_reason = request.POST.get("late_reason", "").strip()

    latitude = request.POST.get("latitude") or None
    longitude = request.POST.get("longitude") or None
    accuracy = request.POST.get("location_accuracy") or None

    staff = get_object_or_404(
        StaffProfile.objects.select_related("user", "branch"),
        pk=staff_id,
    )

    if staff.branch_id != qr.branch_id:
        messages.error(request, "This staff does not belong to this branch.")
        return redirect("staff_scan_page", token=qr.token)

    setting = StaffPayrollSetting.objects.filter(
        staff=staff,
        is_active=True,
    ).first()

    if not setting:
        messages.error(request, "Payroll setting not found. Please contact admin.")
        return redirect("staff_scan_page", token=qr.token)

    if setting.attendance_pin and pin != setting.attendance_pin:
        messages.error(request, "Wrong PIN.")
        return redirect("staff_scan_page", token=qr.token)

    now = timezone.localtime()
    today = timezone.localdate()
    shift = _get_active_shift(staff)

    distance, location_status, is_suspicious, suspicious_reason = _check_location(
        branch=qr.branch,
        latitude=latitude,
        longitude=longitude,
    )

    attendance, created = StaffAttendance.objects.get_or_create(
        staff=staff,
        date=today,
        defaults={
            "branch": qr.branch,
            "shift": shift,
            "scan_method": "branch_qr",
        },
    )

    attendance.branch = qr.branch
    attendance.shift = shift
    attendance.scan_method = "branch_qr"
    attendance.latitude = latitude
    attendance.longitude = longitude
    attendance.location_accuracy = accuracy
    attendance.distance_from_branch_meters = distance
    attendance.device_info = request.META.get("HTTP_USER_AGENT", "")
    attendance.ip_address = _get_ip_address(request)
    attendance.is_suspicious = is_suspicious
    attendance.suspicious_reason = suspicious_reason

    staff_name = _staff_name(staff).upper()
    position = _staff_position(staff)
    branch_name = qr.branch.name if qr.branch else "No Branch"

    if action == "check_out":
        attendance.check_out_time = now
        attendance.save()

        telegram_text = (
            f"{staff_name} checked out 👋\n"
            f"Position: {position}\n"
            f"Branch: {branch_name}"
        )

        if attendance.is_suspicious:
            if distance is not None:
                telegram_text += f"\n⚠️ Wrong GPS: {distance}m from branch"
            else:
                telegram_text += f"\n⚠️ GPS issue: {location_status}"

        send_staff_telegram_message(telegram_text)

        messages.success(request, "Check out recorded.")
        return redirect("staff_scan_page", token=qr.token)

    status, minutes_value, status_text, status_icon = _check_arrival_status(
        today=today,
        now=now,
        shift=shift,
    )

    if status == "late" and not late_reason:
        messages.error(request, "You are late. Please write the late reason before check in.")
        return redirect("staff_scan_page", token=qr.token)

    attendance.check_in_time = now
    attendance.status = status

    if status == "late":
        attendance.late_minutes = minutes_value
        attendance.note = f"Late reason: {late_reason}"
    else:
        attendance.late_minutes = 0
        if not attendance.note:
            attendance.note = ""

    attendance.save()

    telegram_text = (
        f"{staff_name} checked in {status_icon} {status_text}\n"
        f"Position: {position}\n"
        f"Branch: {branch_name}"
    )

    if status == "late":
        telegram_text += f"\nReason: {late_reason}"

    if attendance.is_suspicious:
        if distance is not None:
            telegram_text += f"\n⚠️ Wrong GPS: {distance}m from branch"
        else:
            telegram_text += f"\n⚠️ GPS issue: {location_status}"

    send_staff_telegram_message(telegram_text)

    messages.success(request, "Check in recorded.")
    return redirect("staff_scan_page", token=qr.token)


# =========================================================
# MY STAFF PAGE / PERMISSION
# =========================================================

@login_required
def staff_my_dashboard(request):
    staff = _get_staff_profile_from_user(request.user)

    if not staff:
        messages.error(request, "Your staff profile is not set.")
        return redirect("dashboard")

    today = timezone.localdate()
    month_start = today.replace(day=1)

    attendances = (
        StaffAttendance.objects
        .select_related("branch", "shift")
        .filter(staff=staff)
        .order_by("-date")[:30]
    )

    month_attendances = StaffAttendance.objects.filter(
        staff=staff,
        date__gte=month_start,
        date__lte=today,
    )

    late_days = month_attendances.filter(status="late").count()

    late_minutes = (
        month_attendances.aggregate(total=Sum("late_minutes")).get("total")
        or 0
    )

    permissions = (
        StaffPermissionRequest.objects
        .filter(staff=staff)
        .order_by("-created_at")[:10]
    )

    commissions = (
        StaffCommission.objects
        .select_related("pet_sale")
        .filter(staff=staff)
        .order_by("-created_at")[:20]
    )

    total_commission = (
        StaffCommission.objects
        .filter(staff=staff, status__in=["pending", "approved", "paid"])
        .aggregate(total=Sum("commission_amount"))
        .get("total")
        or Decimal("0.00")
    )

    pet_sales_count = PetSale.objects.filter(seller=request.user).count()

    return render(request, "staffs/staff_my_dashboard.html", {
        "staff": staff,
        "attendances": attendances,
        "permissions": permissions,
        "commissions": commissions,
        "late_days": late_days,
        "late_minutes": late_minutes,
        "pet_sales_count": pet_sales_count,
        "total_commission": total_commission,
    })


@login_required
def staff_permission_create(request):
    staff = _get_staff_profile_from_user(request.user)

    if not staff:
        messages.error(request, "Your staff profile is not set.")
        return redirect("dashboard")

    if request.method == "POST":
        request_type = request.POST.get("request_type", "other")
        date_from = parse_date(request.POST.get("date_from", ""))
        date_to = parse_date(request.POST.get("date_to", ""))
        time_from = parse_time(request.POST.get("time_from", "") or "")
        time_to = parse_time(request.POST.get("time_to", "") or "")
        reason = request.POST.get("reason", "").strip()
        proof_photo = request.FILES.get("proof_photo")

        if not date_from or not date_to or not reason:
            messages.error(request, "Please fill date and reason.")
            return redirect("staff_permission_create")

        permission = StaffPermissionRequest.objects.create(
            staff=staff,
            request_type=request_type,
            date_from=date_from,
            date_to=date_to,
            time_from=time_from,
            time_to=time_to,
            reason=reason,
            proof_photo=proof_photo,
        )

        branch_name = staff.branch.name if staff.branch else "No Branch"

        telegram_text = (
            "📝 Staff Permission Request\n"
            f"Staff: {_staff_name(staff)}\n"
            f"Position: {_staff_position(staff)}\n"
            f"Branch: {branch_name}\n"
            f"Type: {permission.get_request_type_display()}\n"
            f"Date: {date_from.strftime('%d/%m/%Y')} → {date_to.strftime('%d/%m/%Y')}\n"
            f"Time: {time_from or '-'} → {time_to or '-'}\n"
            f"Reason: {reason}"
        )

        send_staff_telegram_message(telegram_text)

        messages.success(request, "Permission request submitted.")
        return redirect("staff_my_dashboard")

    return render(request, "staffs/staff_permission_form.html")


# =========================================================
# STAFF SETTINGS
# =========================================================

@login_required
def staff_setting_list(request):
    if not request.user.has_perm("auth.view_user"):
        messages.error(request, "You do not have permission to manage staff settings.")
        return redirect("staff_my_dashboard")

    q = request.GET.get("q", "").strip()

    staffs = (
        StaffProfile.objects
        .select_related("user", "branch", "payroll_setting")
        .prefetch_related("payroll_shifts")
        .order_by("branch__name", "user__username")
    )

    if q:
        staffs = staffs.filter(
            Q(user__username__icontains=q)
            | Q(user__first_name__icontains=q)
            | Q(user__last_name__icontains=q)
            | Q(branch__name__icontains=q)
        ).distinct()

    return render(request, "staffs/staff_setting_list.html", {
        "staffs": staffs,
        "q": q,
    })


@login_required
def staff_setting_create(request):
    if not request.user.has_perm("auth.view_user"):
        messages.error(request, "You do not have permission to create staff settings.")
        return redirect("staff_my_dashboard")

    staffs = (
        StaffProfile.objects
        .select_related("user", "branch")
        .filter(user__is_active=True)
        .order_by("branch__name", "user__username")
    )

    if request.method == "POST":
        staff_id = request.POST.get("staff")
        staff = get_object_or_404(StaffProfile, id=staff_id)

        setting, created = StaffPayrollSetting.objects.get_or_create(
            staff=staff,
            defaults={
                "base_salary": request.POST.get("base_salary") or 0,
                "start_work_date": request.POST.get("start_work_date") or timezone.localdate(),
                "salary_cycle_start_day": request.POST.get("salary_cycle_start_day") or 1,
                "salary_open_after_days": request.POST.get("salary_open_after_days") or 6,
                "attendance_pin": request.POST.get("attendance_pin", "").strip(),
                "default_commission_rate": request.POST.get("default_commission_rate") or 5,
                "commission_enabled": bool(request.POST.get("commission_enabled")),
                "is_active": True,
                "note": request.POST.get("note", "").strip(),
            },
        )

        if not created:
            messages.error(request, "This staff already has payroll setting. Please edit instead.")
            return redirect("staff_setting_edit", staff_id=staff.id)

        shift_start = request.POST.get("shift_start")
        shift_end = request.POST.get("shift_end")
        late_after_minutes = request.POST.get("late_after_minutes") or 10

        if shift_start and shift_end:
            StaffShift.objects.create(
                staff=staff,
                name="Default Shift",
                start_time=shift_start,
                end_time=shift_end,
                late_after_minutes=late_after_minutes,
                is_active=True,
            )

        messages.success(request, "Staff payroll setting created.")
        return redirect("staff_setting_list")

    return render(request, "staffs/staff_setting_form.html", {
        "staffs": staffs,
        "setting": None,
        "selected_staff": None,
        "shift": None,
        "title": "Create Staff Setting",
    })


@login_required
def staff_setting_edit(request, staff_id):
    if not request.user.has_perm("auth.view_user"):
        messages.error(request, "You do not have permission to edit staff settings.")
        return redirect("staff_my_dashboard")

    staff = get_object_or_404(
        StaffProfile.objects.select_related("user", "branch"),
        id=staff_id,
    )

    setting, created = StaffPayrollSetting.objects.get_or_create(
        staff=staff,
        defaults={
            "base_salary": 0,
            "start_work_date": timezone.localdate(),
            "salary_cycle_start_day": 1,
            "salary_open_after_days": 6,
            "attendance_pin": "",
            "default_commission_rate": 5,
            "commission_enabled": True,
            "is_active": True,
        },
    )

    shift = (
        StaffShift.objects
        .filter(staff=staff, is_active=True)
        .order_by("start_time")
        .first()
    )

    if request.method == "POST":
        setting.base_salary = request.POST.get("base_salary") or 0
        setting.start_work_date = request.POST.get("start_work_date") or timezone.localdate()
        setting.salary_cycle_start_day = request.POST.get("salary_cycle_start_day") or 1
        setting.salary_open_after_days = request.POST.get("salary_open_after_days") or 6
        setting.attendance_pin = request.POST.get("attendance_pin", "").strip()
        setting.default_commission_rate = request.POST.get("default_commission_rate") or 5
        setting.commission_enabled = bool(request.POST.get("commission_enabled"))
        setting.is_active = bool(request.POST.get("is_active"))
        setting.note = request.POST.get("note", "").strip()
        setting.save()

        shift_start = request.POST.get("shift_start")
        shift_end = request.POST.get("shift_end")
        late_after_minutes = request.POST.get("late_after_minutes") or 10

        if shift_start and shift_end:
            if not shift:
                shift = StaffShift(staff=staff, name="Default Shift")

            shift.start_time = shift_start
            shift.end_time = shift_end
            shift.late_after_minutes = late_after_minutes
            shift.is_active = True
            shift.save()

        messages.success(request, "Staff payroll setting updated.")
        return redirect("staff_setting_list")

    return render(request, "staffs/staff_setting_form.html", {
        "staffs": None,
        "setting": setting,
        "selected_staff": staff,
        "shift": shift,
        "title": "Edit Staff Setting",
    })


# =========================================================
# ATTENDANCE REPORT / MANUAL ADJUST
# =========================================================

@login_required
def staff_attendance_report(request):
    if not request.user.has_perm("auth.view_user"):
        messages.error(request, "You do not have permission to view attendance report.")
        return redirect("staff_my_dashboard")

    today = timezone.localdate()
    month_start = today.replace(day=1)
    month_end_day = calendar.monthrange(today.year, today.month)[1]
    month_end = today.replace(day=month_end_day)

    staff_id = request.GET.get("staff", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()

    if not date_from:
        date_from = month_start.strftime("%Y-%m-%d")

    if not date_to:
        date_to = month_end.strftime("%Y-%m-%d")

    parsed_from = parse_date(date_from)
    parsed_to = parse_date(date_to)

    staffs = (
        StaffProfile.objects
        .select_related("user", "branch")
        .filter(user__is_active=True)
        .order_by("branch__name", "user__username")
    )

    selected_staff = None
    selected_staff_label = "All Staff"

    attendances = (
        StaffAttendance.objects
        .select_related("staff", "staff__user", "branch", "shift", "created_by")
        .all()
        .order_by("-date", "staff__user__username")
    )

    if staff_id:
        selected_staff = get_object_or_404(
            StaffProfile.objects.select_related("user", "branch"),
            id=staff_id,
        )

        selected_staff_label = (
            selected_staff.user.get_full_name()
            or selected_staff.user.username
        )

        attendances = attendances.filter(staff=selected_staff)

    if parsed_from:
        attendances = attendances.filter(date__gte=parsed_from)

    if parsed_to:
        attendances = attendances.filter(date__lte=parsed_to)

    total_records = attendances.count()
    present_days = attendances.filter(status="present").count()
    late_days = attendances.filter(status="late").count()
    absent_days = attendances.filter(status="absent").count()
    permission_days = attendances.filter(status="permission").count()
    leave_days = attendances.filter(status="leave").count()

    total_late_minutes = (
        attendances.aggregate(total=Sum("late_minutes")).get("total")
        or 0
    )

    attendance_rows = []

    for row in attendances:
        day_sales = PetSale.objects.filter(
            seller=row.staff.user,
            created_at__date=row.date,
        )

        pet_total_sold_count = day_sales.count()

        pet_total_sold_amount = (
            day_sales.aggregate(total=Sum("sale_price")).get("total")
            or Decimal("0.00")
        )

        attendance_rows.append({
            "attendance": row,
            "pet_total_sold_count": pet_total_sold_count,
            "pet_total_sold_amount": pet_total_sold_amount,
        })

    return render(request, "staffs/staff_attendance_report.html", {
        "staffs": staffs,
        "selected_staff": selected_staff,
        "selected_staff_id": staff_id,
        "selected_staff_label": selected_staff_label,

        "date_from": date_from,
        "date_to": date_to,

        "attendances": attendances,
        "attendance_rows": attendance_rows,

        "total_records": total_records,
        "present_days": present_days,
        "late_days": late_days,
        "absent_days": absent_days,
        "permission_days": permission_days,
        "leave_days": leave_days,
        "total_late_minutes": total_late_minutes,
    })


@login_required
def staff_attendance_adjust(request):
    if not request.user.has_perm("auth.view_user"):
        messages.error(request, "You do not have permission to adjust attendance.")
        return redirect("staff_my_dashboard")

    staffs = (
        StaffProfile.objects
        .select_related("user", "branch")
        .filter(user__is_active=True)
        .order_by("branch__name", "user__username")
    )

    today = timezone.localdate()

    if request.method == "POST":
        staff_id = request.POST.get("staff")
        date_value = parse_date(request.POST.get("date", ""))
        status = request.POST.get("status", "present")
        check_in_value = request.POST.get("check_in_time", "").strip()
        check_out_value = request.POST.get("check_out_time", "").strip()
        late_minutes = request.POST.get("late_minutes") or 0
        note = request.POST.get("note", "").strip()

        if not staff_id or not date_value:
            messages.error(request, "Please select staff and date.")
            return redirect("staff_attendance_adjust")

        staff = get_object_or_404(
            StaffProfile.objects.select_related("user", "branch"),
            id=staff_id,
        )

        shift = _get_active_shift(staff)

        attendance, created = StaffAttendance.objects.get_or_create(
            staff=staff,
            date=date_value,
            defaults={
                "branch": staff.branch,
                "shift": shift,
                "scan_method": "manual",
                "created_by": request.user,
            },
        )

        attendance.branch = staff.branch
        attendance.shift = shift
        attendance.scan_method = "manual"
        attendance.created_by = request.user
        attendance.status = status
        attendance.late_minutes = int(late_minutes or 0)
        attendance.device_info = f"Manual adjustment by {request.user.username}"
        attendance.ip_address = _get_ip_address(request)
        attendance.is_suspicious = False
        attendance.suspicious_reason = ""

        current_timezone = timezone.get_current_timezone()

        if check_in_value:
            parsed_check_in = parse_time(check_in_value)
            if parsed_check_in:
                attendance.check_in_time = timezone.make_aware(
                    datetime.combine(date_value, parsed_check_in),
                    current_timezone,
                )
        elif status in ["present", "late"] and shift:
            attendance.check_in_time = timezone.make_aware(
                datetime.combine(date_value, shift.start_time),
                current_timezone,
            )

        if check_out_value:
            parsed_check_out = parse_time(check_out_value)
            if parsed_check_out:
                attendance.check_out_time = timezone.make_aware(
                    datetime.combine(date_value, parsed_check_out),
                    current_timezone,
                )

        attendance.note = note or "Manual adjustment: staff forgot to scan."
        attendance.save()

        staff_name = _staff_name(staff)
        branch_name = staff.branch.name if staff.branch else "No Branch"

        telegram_text = (
            "🛠 Staff Attendance Adjusted\n"
            f"Staff: {staff_name}\n"
            f"Position: {_staff_position(staff)}\n"
            f"Branch: {branch_name}\n"
            f"Date: {date_value.strftime('%d/%m/%Y')}\n"
            f"Status: {attendance.get_status_display()}\n"
            f"Late: {_format_minutes(attendance.late_minutes)}\n"
            f"Note: {attendance.note}"
        )

        send_staff_telegram_message(telegram_text)

        messages.success(request, "Attendance adjusted successfully.")

        report_url = (
            f"{reverse('staff_attendance_report')}"
            f"?staff={staff.id}&date_from={date_value}&date_to={date_value}"
        )

        return redirect(report_url)

    return render(request, "staffs/staff_attendance_adjust.html", {
        "staffs": staffs,
        "today": today,
    })


@login_required
def branch_location_setting(request):
    if not request.user.has_perm("auth.view_user"):
        messages.error(request, "You do not have permission to manage branch GPS.")
        return redirect("staff_my_dashboard")

    branches = Branch.objects.filter(is_active=True).order_by("name")
    selected_branch_id = request.GET.get("branch", "").strip()

    if request.method == "POST":
        branch_id = request.POST.get("branch", "").strip()
        latitude = request.POST.get("latitude", "").strip()
        longitude = request.POST.get("longitude", "").strip()
        allowed_radius_meters = request.POST.get("allowed_radius_meters", "").strip() or "100"

        if not branch_id:
            messages.error(request, "Please select branch.")
            return redirect("branch_location_setting")

        branch = get_object_or_404(Branch, id=branch_id)

        branch.latitude = latitude or None
        branch.longitude = longitude or None
        branch.allowed_radius_meters = int(allowed_radius_meters or 100)
        branch.save()

        messages.success(request, f"{branch.name} GPS location updated.")
        return redirect(f"{reverse('branch_location_setting')}?branch={branch.id}")

    selected_branch = None

    if selected_branch_id:
        selected_branch = branches.filter(id=selected_branch_id).first()

    return render(request, "staffs/branch_location_setting.html", {
        "branches": branches,
        "selected_branch": selected_branch,
        "selected_branch_id": selected_branch_id,
    })

# =========================================================
# STAFF SALARY CENTER V2
# =========================================================

def _month_add(year, month, add_months=1):
    month_index = (year * 12 + (month - 1)) + add_months
    new_year = month_index // 12
    new_month = month_index % 12 + 1
    return new_year, new_month


def _safe_day_date(year, month, day):
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(int(day or 1), last_day))


def _salary_cycle_for_setting(setting, today=None):
    today = today or timezone.localdate()
    cycle_day = int(setting.salary_cycle_start_day or 1)

    this_month_start = _safe_day_date(today.year, today.month, cycle_day)

    if today >= this_month_start:
        period_start = this_month_start
    else:
        py, pm = _month_add(today.year, today.month, -1)
        period_start = _safe_day_date(py, pm, cycle_day)

    ny, nm = _month_add(period_start.year, period_start.month, 1)
    next_period_start = _safe_day_date(ny, nm, cycle_day)
    period_end = next_period_start - timedelta(days=1)
    expected_open_date = period_end + timedelta(days=int(setting.salary_open_after_days or 0))

    return period_start, period_end, expected_open_date


def _pet_sale_bonus(dog_count):
    dog_count = int(dog_count or 0)
    if dog_count >= 60:
        return Decimal("270.00")
    if dog_count >= 45:
        return Decimal("180.00")
    if dog_count >= 30:
        return Decimal("100.00")
    return Decimal("0.00")


def _get_staff_from_user(user):
    if not user:
        return None
    try:
        return user.staff_profile
    except Exception:
        return None


def _pet_sale_amount(sale):
    try:
        return Decimal(sale.final_price or 0)
    except Exception:
        return Decimal(sale.sale_price or 0) - Decimal(getattr(sale, "discount_amount", 0) or 0)


def _sync_missing_pet_sale_commissions(period_start=None, period_end=None):
    qs = PetSale.objects.filter(status="completed").select_related("seller", "created_by")

    if period_start:
        qs = qs.filter(completed_at__date__gte=period_start)
    if period_end:
        qs = qs.filter(completed_at__date__lte=period_end)

    created_count = 0

    for sale in qs:
        if StaffCommission.objects.filter(pet_sale=sale).exists():
            continue

        seller_user = sale.seller or sale.created_by
        staff = _get_staff_from_user(seller_user)
        if not staff:
            continue

        setting = StaffPayrollSetting.objects.filter(staff=staff, is_active=True).first()
        if not setting or not setting.commission_enabled:
            continue

        sale_amount = _pet_sale_amount(sale)
        rate = setting.pet_sale_commission_rate or setting.default_commission_rate or Decimal("0")

        StaffCommission.objects.create(
            staff=staff,
            pet_sale=sale,
            sale_amount=sale_amount,
            commission_rate=rate,
            status="approved",
            approved_at=timezone.now(),
            note="Auto-created from completed pet sale.",
        )
        created_count += 1

    return created_count


def _salary_preview_for_setting(setting, today=None):
    today = today or timezone.localdate()
    staff = setting.staff
    period_start, period_end, expected_open_date = _salary_cycle_for_setting(setting, today)

    payroll = PayrollRecord.objects.filter(
        staff=staff,
        period_start=period_start,
        period_end=period_end,
    ).order_by("-id").first()

    attendances = StaffAttendance.objects.filter(
        staff=staff,
        date__gte=period_start,
        date__lte=period_end,
    )

    late_qs = attendances.filter(status="late")
    late_count = late_qs.count()
    late_minutes = late_qs.aggregate(total=Sum("late_minutes"))["total"] or 0

    absent_count = attendances.filter(status="absent").count()
    leave_count = attendances.filter(status="leave").count()
    permission_count = attendances.filter(status="permission").count()
    half_day_count = attendances.filter(status="half_day").count()

    allowed_late = int(setting.allowed_late_times or 3)
    extra_late_day_off = 0
    if allowed_late > 0 and late_count > allowed_late:
        extra_late_day_off = ((late_count - allowed_late - 1) // allowed_late) + 1
    elif allowed_late == 0 and late_count > 0:
        extra_late_day_off = late_count

    day_off_used = absent_count + leave_count + permission_count + half_day_count + extra_late_day_off
    allowed_day_off = int(setting.allowed_day_off_per_month or 0)
    over_day_off = max(day_off_used - allowed_day_off, 0)
    unused_day_off = max(allowed_day_off - day_off_used, 0)

    attendance_bonus = Decimal(setting.no_late_bonus or 0) if late_count == 0 else Decimal("0.00")
    unused_day_off_bonus = Decimal(unused_day_off) * Decimal(setting.unused_day_off_bonus_per_day or 0)
    day_off_deduction = Decimal(over_day_off) * Decimal(setting.over_day_off_deduction_per_day or 0)
    late_deduction = Decimal(extra_late_day_off) * Decimal(setting.late_deduction_per_day or 0)
    absent_deduction = Decimal(absent_count) * Decimal(setting.absent_deduction_per_day or 0)

    pet_commission_qs = StaffCommission.objects.filter(
        staff=staff,
        status__in=["pending", "approved"],
        payroll_record__isnull=True,
        created_at__date__gte=period_start,
        created_at__date__lte=period_end,
    )
    pet_commission = pet_commission_qs.aggregate(total=Sum("commission_amount"))["total"] or Decimal("0.00")

    grooming_commission_qs = GroomingCommission.objects.filter(
        staff=staff,
        status__in=["pending", "approved"],
        payroll_record__isnull=True,
        created_at__date__gte=period_start,
        created_at__date__lte=period_end,
    )
    grooming_commission = grooming_commission_qs.aggregate(total=Sum("commission_amount"))["total"] or Decimal("0.00")

    pet_sales = PetSale.objects.filter(
        status="completed",
        seller=staff.user,
        completed_at__date__gte=period_start,
        completed_at__date__lte=period_end,
    )
    dog_count = 0
    for sale in pet_sales:
        try:
            pet_type = sale.pet.pet_type if sale.pet else sale.preorder_pet_type
        except Exception:
            pet_type = sale.preorder_pet_type
        if pet_type == "dog":
            dog_count += 1

    pet_target_bonus = _pet_sale_bonus(dog_count)
    total_commission = Decimal(pet_commission or 0) + Decimal(grooming_commission or 0)

    net_salary = (
        Decimal(setting.base_salary or 0)
        + total_commission
        + attendance_bonus
        + unused_day_off_bonus
        + pet_target_bonus
        - day_off_deduction
        - late_deduction
        - absent_deduction
    )

    if payroll and payroll.status == "paid":
        status = "paid"
    elif payroll:
        status = payroll.status
    elif today > expected_open_date:
        status = "overdue"
    elif today == expected_open_date:
        status = "open_today"
    elif 0 <= (expected_open_date - today).days <= 5:
        status = "opening_soon"
    else:
        status = "waiting"

    days_left = (expected_open_date - today).days

    return {
        "setting": setting,
        "staff": staff,
        "staff_name": _staff_name(staff),
        "branch": getattr(staff, "branch", None),
        "period_start": period_start,
        "period_end": period_end,
        "expected_open_date": expected_open_date,
        "days_left": days_left,
        "status": status,
        "payroll": payroll,
        "base_salary": Decimal(setting.base_salary or 0),
        "pet_commission": Decimal(pet_commission or 0),
        "grooming_commission": Decimal(grooming_commission or 0),
        "total_commission": total_commission,
        "dog_count": dog_count,
        "pet_target_bonus": pet_target_bonus,
        "late_count": late_count,
        "late_minutes": late_minutes,
        "allowed_late": allowed_late,
        "extra_late_day_off": extra_late_day_off,
        "allowed_day_off": allowed_day_off,
        "day_off_used": day_off_used,
        "over_day_off": over_day_off,
        "unused_day_off": unused_day_off,
        "attendance_bonus": attendance_bonus,
        "unused_day_off_bonus": unused_day_off_bonus,
        "day_off_deduction": day_off_deduction,
        "late_deduction": late_deduction,
        "absent_deduction": absent_deduction,
        "absent_count": absent_count,
        "permission_count": permission_count,
        "net_salary": net_salary,
    }


@login_required
def staff_salary_dashboard(request):
    if not request.user.has_perm("auth.view_user"):
        messages.error(request, "You do not have permission to view salary.")
        return redirect("staff_my_dashboard")

    today = timezone.localdate()
    selected_branch_id = request.GET.get("branch", "").strip()
    status_filter = request.GET.get("status", "").strip()
    q = request.GET.get("q", "").strip()

    settings_qs = (
        StaffPayrollSetting.objects
        .select_related("staff", "staff__user", "staff__branch")
        .filter(is_active=True)
        .order_by("staff__branch__name", "staff__user__first_name", "staff__user__username")
    )

    if selected_branch_id:
        settings_qs = settings_qs.filter(staff__branch_id=selected_branch_id)

    if q:
        settings_qs = settings_qs.filter(
            Q(staff__user__username__icontains=q)
            | Q(staff__user__first_name__icontains=q)
            | Q(staff__user__last_name__icontains=q)
        )

    # Keep pet sale commission list up-to-date for this payroll cycle area.
    _sync_missing_pet_sale_commissions()

    rows = [_salary_preview_for_setting(setting, today) for setting in settings_qs]

    if status_filter:
        rows = [row for row in rows if row["status"] == status_filter]

    rows.sort(key=lambda row: (row["expected_open_date"], row["staff_name"]))

    totals = {
        "staff_count": len(rows),
        "opening_soon": sum(1 for row in rows if row["status"] == "opening_soon"),
        "open_today": sum(1 for row in rows if row["status"] == "open_today"),
        "overdue": sum(1 for row in rows if row["status"] == "overdue"),
        "net_salary": sum((row["net_salary"] for row in rows), Decimal("0.00")),
        "commission": sum((row["total_commission"] for row in rows), Decimal("0.00")),
    }

    branches = Branch.objects.filter(is_active=True).order_by("name")

    return render(request, "staffs/staff_salary_dashboard.html", {
        "rows": rows,
        "totals": totals,
        "branches": branches,
        "selected_branch_id": selected_branch_id,
        "status_filter": status_filter,
        "q": q,
        "today": today,
    })


@login_required
def staff_commission_list(request):
    if not request.user.has_perm("auth.view_user"):
        messages.error(request, "You do not have permission to view commissions.")
        return redirect("staff_my_dashboard")

    _sync_missing_pet_sale_commissions()

    commission_type = request.GET.get("type", "").strip()
    status = request.GET.get("status", "").strip()
    q = request.GET.get("q", "").strip()
    date_from = parse_date(request.GET.get("date_from", "") or "")
    date_to = parse_date(request.GET.get("date_to", "") or "")

    pet_qs = StaffCommission.objects.select_related(
        "staff", "staff__user", "staff__branch", "pet_sale", "payroll_record"
    ).order_by("-created_at")

    grooming_qs = GroomingCommission.objects.select_related(
        "staff", "staff__user", "staff__branch", "sale", "payroll_record"
    ).order_by("-created_at")

    if status:
        pet_qs = pet_qs.filter(status=status)
        grooming_qs = grooming_qs.filter(status=status)
    if date_from:
        pet_qs = pet_qs.filter(created_at__date__gte=date_from)
        grooming_qs = grooming_qs.filter(created_at__date__gte=date_from)
    if date_to:
        pet_qs = pet_qs.filter(created_at__date__lte=date_to)
        grooming_qs = grooming_qs.filter(created_at__date__lte=date_to)
    if q:
        staff_filter = (
            Q(staff__user__username__icontains=q)
            | Q(staff__user__first_name__icontains=q)
            | Q(staff__user__last_name__icontains=q)
        )
        pet_qs = pet_qs.filter(staff_filter | Q(pet_sale__id__icontains=q))
        grooming_qs = grooming_qs.filter(staff_filter | Q(sale__id__icontains=q))

    rows = []

    if commission_type in ["", "pet"]:
        for item in pet_qs[:300]:
            rows.append({
                "created_at": item.created_at,
                "date": item.created_at.date(),
                "type": "Pet Sale",
                "staff": item.staff,
                "branch": getattr(item.staff, "branch", None),
                "source": f"Pet Sale #{item.pet_sale_id}",
                "sale_amount": item.sale_amount,
                "rate": item.commission_rate,
                "amount": item.commission_amount,
                "status": item.status,
                "payroll": item.payroll_record,
                "note": item.note,
            })

    if commission_type in ["", "grooming"]:
        for item in grooming_qs[:300]:
            rows.append({
                "created_at": item.created_at,
                "date": item.created_at.date(),
                "type": "Grooming",
                "staff": item.staff,
                "branch": item.branch or getattr(item.staff, "branch", None),
                "source": f"POS Sale #{item.sale_id}",
                "sale_amount": item.sale_amount,
                "rate": item.commission_rate,
                "amount": item.commission_amount,
                "status": item.status,
                "payroll": item.payroll_record,
                "note": item.note,
            })

    rows.sort(key=lambda row: row["created_at"], reverse=True)

    totals = {
        "count": len(rows),
        "amount": sum((Decimal(row["amount"] or 0) for row in rows), Decimal("0.00")),
        "pending": sum(1 for row in rows if row["status"] == "pending"),
        "approved": sum(1 for row in rows if row["status"] == "approved"),
        "paid": sum(1 for row in rows if row["status"] == "paid"),
    }

    return render(request, "staffs/staff_commission_list.html", {
        "rows": rows[:500],
        "totals": totals,
        "commission_type": commission_type,
        "status": status,
        "q": q,
        "date_from": date_from,
        "date_to": date_to,
    })


@login_required
def staff_salary_open(request, staff_id):
    if not request.user.has_perm("auth.view_user"):
        messages.error(request, "You do not have permission to open salary.")
        return redirect("staff_my_dashboard")

    setting = get_object_or_404(
        StaffPayrollSetting.objects.select_related("staff", "staff__user", "staff__branch"),
        staff_id=staff_id,
        is_active=True,
    )

    preview = _salary_preview_for_setting(setting)

    payroll, created = PayrollRecord.objects.get_or_create(
        staff=setting.staff,
        period_start=preview["period_start"],
        period_end=preview["period_end"],
        defaults={
            "expected_open_date": preview["expected_open_date"],
            "opened_at": timezone.now(),
            "opened_by": request.user,
            "status": "opened",
        },
    )

    payroll.expected_open_date = preview["expected_open_date"]
    payroll.opened_at = payroll.opened_at or timezone.now()
    payroll.opened_by = payroll.opened_by or request.user
    payroll.status = "opened" if payroll.status == "draft" else payroll.status
    payroll.base_salary = preview["base_salary"]
    payroll.pet_sale_commission = preview["pet_commission"]
    payroll.grooming_commission = preview["grooming_commission"]
    payroll.total_commission = preview["total_commission"]
    payroll.dog_sale_count = preview["dog_count"]
    payroll.pet_sale_target_bonus = preview["pet_target_bonus"]
    payroll.allowed_day_off = preview["allowed_day_off"]
    payroll.used_day_off = preview["day_off_used"]
    payroll.over_day_off_days = preview["over_day_off"]
    payroll.unused_day_off_days = preview["unused_day_off"]
    payroll.attendance_bonus = preview["attendance_bonus"]
    payroll.unused_day_off_bonus = preview["unused_day_off_bonus"]
    payroll.day_off_deduction = preview["day_off_deduction"]
    payroll.late_days = preview["late_count"]
    payroll.late_minutes = preview["late_minutes"]
    payroll.absent_days = preview["absent_count"]
    payroll.permission_days = preview["permission_count"]
    payroll.late_deduction = preview["late_deduction"]
    payroll.absent_deduction = preview["absent_deduction"]
    payroll.note = request.POST.get("note", "").strip() if request.method == "POST" else payroll.note
    payroll.save()

    StaffCommission.objects.filter(
        staff=setting.staff,
        status__in=["pending", "approved"],
        payroll_record__isnull=True,
        created_at__date__gte=preview["period_start"],
        created_at__date__lte=preview["period_end"],
    ).update(payroll_record=payroll, status="approved", approved_at=timezone.now())

    GroomingCommission.objects.filter(
        staff=setting.staff,
        status__in=["pending", "approved"],
        payroll_record__isnull=True,
        created_at__date__gte=preview["period_start"],
        created_at__date__lte=preview["period_end"],
    ).update(payroll_record=payroll, status="approved", approved_at=timezone.now())

    PayrollHistory.objects.create(
        payroll=payroll,
        action="opened" if created else "edited",
        created_by=request.user,
        note="Salary opened from Staff Salary Dashboard.",
    )

    messages.success(request, f"Salary opened for {preview['staff_name']}.")
    return redirect("payroll_record_detail", pk=payroll.pk)


@login_required
def payroll_record_detail(request, pk):
    if not request.user.has_perm("auth.view_user"):
        messages.error(request, "You do not have permission to view salary.")
        return redirect("staff_my_dashboard")

    payroll = get_object_or_404(
        PayrollRecord.objects.select_related("staff", "staff__user", "staff__branch"),
        pk=pk,
    )

    pet_commissions = payroll.commissions.select_related("pet_sale").all()
    grooming_commissions = payroll.grooming_commissions.select_related("sale", "branch").all()
    histories = payroll.histories.select_related("created_by").all()

    return render(request, "staffs/payroll_record_detail.html", {
        "payroll": payroll,
        "pet_commissions": pet_commissions,
        "grooming_commissions": grooming_commissions,
        "histories": histories,
    })


@login_required
def payroll_mark_paid(request, pk):
    if not request.user.has_perm("auth.view_user"):
        messages.error(request, "You do not have permission to pay salary.")
        return redirect("staff_my_dashboard")

    payroll = get_object_or_404(PayrollRecord, pk=pk)

    if request.method != "POST":
        return redirect("payroll_record_detail", pk=payroll.pk)

    payroll.status = "paid"
    payroll.paid_at = timezone.now()
    payroll.paid_by = request.user
    payroll.save()

    payroll.commissions.update(status="paid", paid_at=timezone.now())
    payroll.grooming_commissions.update(status="paid", paid_at=timezone.now())

    PayrollHistory.objects.create(
        payroll=payroll,
        action="paid",
        created_by=request.user,
        note="Salary marked as paid.",
    )

    messages.success(request, "Salary marked as paid.")
    return redirect("payroll_record_detail", pk=payroll.pk)
