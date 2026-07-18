from collections import defaultdict
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import F, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date

from inventory.models import Branch, Item
from pos.models import SaleItem
from users.models import StaffProfile

from .models import (
    GroomingHelperWork,
    GroomingWorkRecord,
    GroomingWorkType,
    POSServiceWorkMapping,
    PayrollAdjustment,
    StaffWorkCommissionRule,
)


def _is_manager(user):
    return bool(user.is_superuser or user.has_perm("auth.view_user"))


def _staff_profile(user):
    return getattr(user, "staff_profile", None)


@login_required
def grooming_my_work(request):
    staff = _staff_profile(request.user)
    if not staff:
        messages.error(request, "Your account is not connected to a staff profile.")
        return redirect("dashboard")

    selected_date = parse_date(request.GET.get("date", "")) or timezone.localdate()
    work_types = GroomingWorkType.objects.filter(is_active=True)

    if request.method == "POST":
        work_type = get_object_or_404(work_types, pk=request.POST.get("work_type"))
        try:
            quantity = Decimal(request.POST.get("quantity", "1") or "1")
        except Exception:
            quantity = Decimal("0")
        if quantity <= 0:
            messages.error(request, "Quantity must be more than zero.")
        elif not getattr(staff, "branch_id", None):
            messages.error(request, "Your staff account has no branch.")
        else:
            GroomingWorkRecord.objects.create(
                staff=staff,
                branch=staff.branch,
                work_type=work_type,
                work_date=selected_date,
                quantity=quantity,
                note=request.POST.get("note", "").strip(),
                created_by=request.user,
            )
            messages.success(request, f"Added {work_type.name} × {quantity}.")
        return redirect(f"{request.path}?date={selected_date.isoformat()}")

    records = GroomingWorkRecord.objects.filter(
        staff=staff, work_date=selected_date
    ).select_related("work_type", "branch")
    totals = records.values("work_type__name").annotate(total=Sum("quantity"))

    return render(request, "staffs/grooming_my_work.html", {
        "staff": staff,
        "selected_date": selected_date,
        "work_types": work_types,
        "records": records,
        "totals": totals,
    })


@login_required
def grooming_work_delete(request, pk):
    staff = _staff_profile(request.user)
    record = get_object_or_404(GroomingWorkRecord, pk=pk)
    if request.method == "POST" and record.staff_id == getattr(staff, "id", None) and record.status == "draft":
        record.delete()
        messages.success(request, "Work record deleted.")
    else:
        messages.error(request, "This record cannot be deleted.")
    return redirect("grooming_my_work")


@login_required
def grooming_daily_comparison(request):
    if not _is_manager(request.user):
        messages.error(request, "Only admin can see POS comparison.")
        return redirect("grooming_my_work")

    selected_date = parse_date(request.GET.get("date", "")) or timezone.localdate()
    branch_id = request.GET.get("branch", "").strip()
    branch = Branch.objects.filter(pk=branch_id).first() if branch_id else Branch.objects.filter(is_active=True).first()

    expected = defaultdict(lambda: Decimal("0"))
    if branch:
        mapping_rows = (
            SaleItem.objects
            .filter(sale__created_at__date=selected_date, sale__branch=branch)
            .filter(item__grooming_work_mappings__is_active=True)
            .values(
                "item__grooming_work_mappings__work_type_id",
                "item__grooming_work_mappings__work_type__name",
                "item__grooming_work_mappings__work_type__sort_order",
            )
            .annotate(total=Sum(F("quantity") * F("item__grooming_work_mappings__quantity")))
        )
        for row in mapping_rows:
            expected[row["item__grooming_work_mappings__work_type_id"]] += Decimal(row["total"] or 0)

    staff_totals = {
        row["work_type_id"]: Decimal(row["total"] or 0)
        for row in GroomingWorkRecord.objects.filter(
            work_date=selected_date, branch=branch
        ).exclude(status="rejected").values("work_type_id").annotate(total=Sum("quantity"))
    } if branch else {}

    helper_totals = {
        row["work_type_id"]: Decimal(row["total"] or 0)
        for row in GroomingHelperWork.objects.filter(
            work_date=selected_date, branch=branch
        ).values("work_type_id").annotate(total=Sum("quantity"))
    } if branch else {}

    work_types = GroomingWorkType.objects.filter(is_active=True)
    rows = []
    for work_type in work_types:
        expected_qty = expected.get(work_type.id, Decimal("0"))
        staff_qty = staff_totals.get(work_type.id, Decimal("0"))
        helper_qty = helper_totals.get(work_type.id, Decimal("0"))
        rows.append({
            "work_type": work_type,
            "expected": expected_qty,
            "staff": staff_qty,
            "helper": helper_qty,
            "difference": staff_qty + helper_qty - expected_qty,
        })

    staff_records = GroomingWorkRecord.objects.filter(
        work_date=selected_date, branch=branch
    ).select_related("staff__user", "work_type").order_by("staff__user__username", "work_type__sort_order") if branch else []

    return render(request, "staffs/grooming_daily_comparison.html", {
        "selected_date": selected_date,
        "branch": branch,
        "branches": Branch.objects.filter(is_active=True),
        "rows": rows,
        "staff_records": staff_records,
        "work_types": work_types,
    })


@login_required
def grooming_helper_add(request):
    if not _is_manager(request.user) or request.method != "POST":
        return redirect("grooming_daily_comparison")
    branch = get_object_or_404(Branch, pk=request.POST.get("branch"))
    work_type = get_object_or_404(GroomingWorkType, pk=request.POST.get("work_type"))
    selected_date = parse_date(request.POST.get("work_date", "")) or timezone.localdate()
    try:
        quantity = Decimal(request.POST.get("quantity", "0") or "0")
    except Exception:
        quantity = Decimal("0")
    if quantity > 0:
        GroomingHelperWork.objects.create(
            branch=branch,
            work_type=work_type,
            work_date=selected_date,
            helper_name=request.POST.get("helper_name", "Helper").strip() or "Helper",
            quantity=quantity,
            note=request.POST.get("note", "").strip(),
            created_by=request.user,
        )
        messages.success(request, "Helper quantity added. No commission will be created.")
    return redirect(f"/staffs/work/comparison/?date={selected_date}&branch={branch.id}")


@login_required
def grooming_confirm_day(request):
    if not _is_manager(request.user) or request.method != "POST":
        return redirect("grooming_daily_comparison")
    selected_date = parse_date(request.POST.get("work_date", "")) or timezone.localdate()
    branch = get_object_or_404(Branch, pk=request.POST.get("branch"))
    updated = GroomingWorkRecord.objects.filter(
        work_date=selected_date, branch=branch, status="draft"
    ).update(status="confirmed", confirmed_by=request.user, confirmed_at=timezone.now())
    messages.success(request, f"Confirmed {updated} work records.")
    return redirect(f"/staffs/work/comparison/?date={selected_date}&branch={branch.id}")


@login_required
def grooming_work_settings(request):
    if not _is_manager(request.user):
        return redirect("grooming_my_work")
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "work_type":
            name = request.POST.get("name", "").strip()
            code = request.POST.get("code", "").strip()
            if name and code:
                GroomingWorkType.objects.get_or_create(code=code, defaults={"name": name})
        elif action == "mapping":
            item = get_object_or_404(Item, pk=request.POST.get("item"))
            work_type = get_object_or_404(GroomingWorkType, pk=request.POST.get("work_type"))
            POSServiceWorkMapping.objects.update_or_create(
                item=item,
                work_type=work_type,
                defaults={"quantity": Decimal(request.POST.get("quantity", "1") or "1"), "is_active": True},
            )
        messages.success(request, "Setting saved.")
        return redirect("grooming_work_settings")

    return render(request, "staffs/grooming_work_settings.html", {
        "work_types": GroomingWorkType.objects.all(),
        "mappings": POSServiceWorkMapping.objects.select_related("item", "work_type"),
        "items": Item.objects.filter(is_active=True).order_by("name"),
    })


@login_required
def staff_work_commission_rules(request):
    if not _is_manager(request.user):
        return redirect("grooming_my_work")
    if request.method == "POST":
        StaffWorkCommissionRule.objects.create(
            staff=get_object_or_404(StaffProfile, pk=request.POST.get("staff")),
            work_type=get_object_or_404(GroomingWorkType, pk=request.POST.get("work_type")),
            calculation_type=request.POST.get("calculation_type", "after_threshold"),
            threshold_quantity=Decimal(request.POST.get("threshold_quantity", "0") or "0"),
            rate_amount=Decimal(request.POST.get("rate_amount", "0") or "0"),
            block_quantity=Decimal(request.POST.get("block_quantity", "1") or "1"),
            effective_from=parse_date(request.POST.get("effective_from", "")) or timezone.localdate(),
            note=request.POST.get("note", "").strip(),
        )
        messages.success(request, "Commission rule added.")
        return redirect("staff_work_commission_rules")

    return render(request, "staffs/staff_work_commission_rules.html", {
        "rules": StaffWorkCommissionRule.objects.select_related("staff__user", "work_type"),
        "staffs": StaffProfile.objects.select_related("user", "branch").filter(user__is_active=True),
        "work_types": GroomingWorkType.objects.filter(is_active=True),
        "calculation_choices": StaffWorkCommissionRule.CALCULATION_CHOICES,
        "today": timezone.localdate(),
    })


@login_required
def payroll_adjustment_list(request):
    if not _is_manager(request.user):
        return redirect("staff_my_dashboard")
    if request.method == "POST":
        PayrollAdjustment.objects.create(
            staff=get_object_or_404(StaffProfile, pk=request.POST.get("staff")),
            adjustment_type=request.POST.get("adjustment_type"),
            amount=Decimal(request.POST.get("amount", "0") or "0"),
            record_date=parse_date(request.POST.get("record_date", "")) or timezone.localdate(),
            reason=request.POST.get("reason", "").strip(),
            note=request.POST.get("note", "").strip(),
            created_by=request.user,
        )
        messages.success(request, "Payroll adjustment saved.")
        return redirect("payroll_adjustment_list")
    return render(request, "staffs/payroll_adjustment_list.html", {
        "rows": PayrollAdjustment.objects.select_related("staff__user", "payroll_record")[:300],
        "staffs": StaffProfile.objects.select_related("user").filter(user__is_active=True),
        "today": timezone.localdate(),
    })
