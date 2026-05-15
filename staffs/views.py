import base64
import calendar
from datetime import datetime
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