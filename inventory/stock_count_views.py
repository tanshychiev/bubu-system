from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, F, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.cost_access import is_owner

from .models import (
    Branch,
    BranchStock,
    ItemVariant,
    StockCountLine,
    StockCountSession,
    StockMovement,
)


# =========================================================
# PERMISSIONS / BRANCH
# =========================================================


def _user_branch(user):
    profile = getattr(user, "staff_profile", None)
    if profile and profile.branch_id:
        return profile.branch
    return None


def _can_count_stock(user):
    if not user or not user.is_authenticated:
        return False

    if is_owner(user):
        return True

    if user.groups.filter(name__iexact="Staff").exists():
        return True

    return user.has_perm("inventory.add_stockmovement")


def _can_confirm_stock_count(user):
    return bool(user and user.is_authenticated and is_owner(user))


def _allowed_sessions(user):
    qs = StockCountSession.objects.all()

    if is_owner(user):
        return qs

    branch = _user_branch(user)
    if not branch:
        return qs.none()

    return qs.filter(branch=branch)


def _get_session_for_user(request, pk, for_update=False):
    qs = _allowed_sessions(request.user)
    if for_update:
        qs = qs.select_for_update()
    return get_object_or_404(qs, pk=pk)


def _selected_branch(request):
    if is_owner(request.user):
        branch_id = (
            request.POST.get("branch")
            or request.GET.get("branch")
            or request.session.get("stock_count_branch_id")
        )

        if branch_id:
            branch = Branch.objects.filter(id=branch_id, is_active=True).first()
            if branch:
                request.session["stock_count_branch_id"] = branch.id
                return branch

        branch = Branch.objects.filter(is_active=True).order_by("name").first()
        if branch:
            request.session["stock_count_branch_id"] = branch.id
        return branch

    return _user_branch(request.user)


# =========================================================
# HELPERS
# =========================================================


def _display_user(user):
    if not user:
        return "-"
    return user.get_full_name() or user.username


def _session_stats(session):
    lines = session.lines.all()
    total = lines.count()
    counted = lines.filter(actual_quantity__isnull=False).count()
    different = lines.filter(actual_quantity__isnull=False).exclude(
        actual_quantity=F("system_quantity")
    ).count()

    return {
        "total": total,
        "counted": counted,
        "remaining": max(total - counted, 0),
        "different": different,
        "percent": round((counted / total) * 100) if total else 0,
    }


def _json_stats(session):
    stats = _session_stats(session)
    return {
        "total": stats["total"],
        "counted": stats["counted"],
        "remaining": stats["remaining"],
        "different": stats["different"],
        "percent": stats["percent"],
    }


def _variant_queryset():
    """
    Item/variant setup is global. Every active physical variant is included
    for every branch, even when that branch has no BranchStock row yet.
    """
    return (
        ItemVariant.objects
        .select_related("item", "item__item_type")
        .filter(
            is_active=True,
            item__is_active=True,
        )
        .exclude(item__unit__in=["service", "pet"])
        .order_by(
            "item__item_type__name",
            "item__name",
            "item__brand",
            "sort_order",
            "id",
        )
    )


def _get_current_quantity(branch, variant):
    stock = BranchStock.objects.filter(branch=branch, variant=variant).first()
    return int(stock.quantity or 0) if stock else 0


def _reason_text(line):
    reason = line.get_reason_code_display() if line.reason_code else ""
    note = (line.reason_note or "").strip()

    if reason and note:
        return f"{reason}: {note}"
    return reason or note or "Stock count adjustment"


# =========================================================
# SESSION LIST / START
# =========================================================


@login_required
def stock_count_list(request):
    if not _can_count_stock(request.user):
        messages.error(request, "You do not have permission to count stock.")
        return redirect("item_list")

    current_branch = _selected_branch(request)
    branches = Branch.objects.filter(is_active=True).order_by("name")

    sessions = _allowed_sessions(request.user).select_related(
        "branch",
        "created_by",
        "submitted_by",
        "confirmed_by",
    ).annotate(
        total_lines=Count("lines", distinct=True),
        counted_lines=Count(
            "lines",
            filter=Q(lines__actual_quantity__isnull=False),
            distinct=True,
        ),
        difference_lines=Count(
            "lines",
            filter=(
                Q(lines__actual_quantity__isnull=False)
                & ~Q(lines__actual_quantity=F("lines__system_quantity"))
            ),
            distinct=True,
        ),
    ).order_by("-created_at", "-id")

    if current_branch:
        sessions = sessions.filter(branch=current_branch)

    return render(
        request,
        "inventory/stock_count_list.html",
        {
            "sessions": sessions,
            "current_branch": current_branch,
            "branches": branches,
            "can_choose_branch": is_owner(request.user),
            "can_confirm": _can_confirm_stock_count(request.user),
        },
    )


@login_required
@require_POST
@transaction.atomic
def stock_count_start(request):
    if not _can_count_stock(request.user):
        messages.error(request, "You do not have permission to count stock.")
        return redirect("item_list")

    branch = _selected_branch(request)
    if not branch:
        messages.error(request, "Please assign a branch before starting stock count.")
        return redirect("stock_count_list")

    active = (
        StockCountSession.objects
        .filter(branch=branch, status__in=["draft", "review"])
        .order_by("-created_at")
        .first()
    )

    if active:
        messages.warning(
            request,
            f"{branch.name} already has an unfinished stock count. Continue it first.",
        )
        return redirect("stock_count_detail", pk=active.pk)

    session = StockCountSession.objects.create(
        branch=branch,
        created_by=request.user,
        note=(request.POST.get("note") or "").strip(),
    )

    variants = list(_variant_queryset())
    stock_map = {
        row.variant_id: int(row.quantity or 0)
        for row in BranchStock.objects.filter(
            branch=branch,
            variant_id__in=[variant.id for variant in variants],
        )
    }

    StockCountLine.objects.bulk_create([
        StockCountLine(
            session=session,
            variant=variant,
            system_quantity=stock_map.get(variant.id, 0),
        )
        for variant in variants
    ])

    messages.success(
        request,
        f"Stock count started for {branch.name}. {len(variants)} SKU(s) loaded.",
    )
    return redirect("stock_count_detail", pk=session.pk)


# =========================================================
# DETAIL / COUNTING
# =========================================================


@login_required
def stock_count_detail(request, pk):
    if not _can_count_stock(request.user):
        messages.error(request, "You do not have permission to count stock.")
        return redirect("item_list")

    session = _get_session_for_user(request, pk)

    lines = (
        session.lines
        .select_related(
            "variant",
            "variant__item",
            "variant__item__item_type",
            "counted_by",
        )
        .order_by(
            "variant__item__item_type__name",
            "variant__item__name",
            "variant__sort_order",
            "variant__id",
        )
    )

    stats = _session_stats(session)

    return render(
        request,
        "inventory/stock_count_detail.html",
        {
            "session": session,
            "lines": lines,
            "stats": stats,
            "reason_choices": StockCountLine.REASON_CHOICES,
            "can_confirm": _can_confirm_stock_count(request.user),
            "is_locked": session.status in ["confirmed", "cancelled"],
            "display_created_by": _display_user(session.created_by),
            "display_submitted_by": _display_user(session.submitted_by),
            "display_confirmed_by": _display_user(session.confirmed_by),
        },
    )


@login_required
@require_POST
@transaction.atomic
def stock_count_save_line(request, pk, line_id):
    if not _can_count_stock(request.user):
        return JsonResponse({"ok": False, "error": "Permission denied."}, status=403)

    session = _get_session_for_user(request, pk, for_update=True)
    if session.status not in ["draft", "review"]:
        return JsonResponse(
            {"ok": False, "error": "This stock count is locked."},
            status=400,
        )

    line = get_object_or_404(
        StockCountLine.objects.select_for_update().select_related("variant"),
        pk=line_id,
        session=session,
    )

    raw_actual = (request.POST.get("actual_quantity") or "").strip()
    reason_code = (request.POST.get("reason_code") or "").strip()
    reason_note = (request.POST.get("reason_note") or "").strip()
    force_recount = request.POST.get("recount") == "1"

    if raw_actual == "":
        line.actual_quantity = None
        line.reason_code = ""
        line.reason_note = ""
        line.counted_by = None
        line.counted_at = None
        line.save(update_fields=[
            "actual_quantity",
            "reason_code",
            "reason_note",
            "counted_by",
            "counted_at",
            "updated_at",
        ])
        return JsonResponse({"ok": True, "cleared": True, "stats": _json_stats(session)})

    try:
        actual = int(raw_actual)
    except (TypeError, ValueError):
        return JsonResponse(
            {"ok": False, "error": "Actual quantity must be a whole number."},
            status=400,
        )

    if actual < 0:
        return JsonResponse(
            {"ok": False, "error": "Actual quantity cannot be negative."},
            status=400,
        )

    # Snapshot the live branch quantity when this SKU is first counted.
    # This keeps the difference tied to the count time, not session creation.
    if line.actual_quantity is None or force_recount:
        line.system_quantity = _get_current_quantity(session.branch, line.variant)

    line.actual_quantity = actual
    line.counted_by = request.user
    line.counted_at = timezone.now()

    difference = actual - int(line.system_quantity or 0)
    if difference == 0:
        line.reason_code = ""
        line.reason_note = ""
    else:
        valid_reason_codes = {value for value, _label in StockCountLine.REASON_CHOICES}
        line.reason_code = reason_code if reason_code in valid_reason_codes else ""
        line.reason_note = reason_note

    line.save(update_fields=[
        "system_quantity",
        "actual_quantity",
        "reason_code",
        "reason_note",
        "counted_by",
        "counted_at",
        "updated_at",
    ])

    return JsonResponse({
        "ok": True,
        "system_quantity": line.system_quantity,
        "actual_quantity": line.actual_quantity,
        "difference": difference,
        "counted_by": _display_user(line.counted_by),
        "counted_at": timezone.localtime(line.counted_at).strftime("%d %b %Y, %H:%M"),
        "needs_reason": difference != 0,
        "stats": _json_stats(session),
    })


@login_required
@require_POST
@transaction.atomic
def stock_count_fill_remaining(request, pk):
    if not _can_count_stock(request.user):
        messages.error(request, "Permission denied.")
        return redirect("item_list")

    session = _get_session_for_user(request, pk, for_update=True)
    if session.status not in ["draft", "review"]:
        messages.error(request, "This stock count is locked.")
        return redirect("stock_count_detail", pk=session.pk)

    lines = list(
        session.lines
        .select_for_update()
        .select_related("variant")
        .filter(actual_quantity__isnull=True)
    )

    now = timezone.now()
    for line in lines:
        current_qty = _get_current_quantity(session.branch, line.variant)
        line.system_quantity = current_qty
        line.actual_quantity = current_qty
        line.reason_code = ""
        line.reason_note = ""
        line.counted_by = request.user
        line.counted_at = now
        line.updated_at = now

    if lines:
        StockCountLine.objects.bulk_update(
            lines,
            [
                "system_quantity",
                "actual_quantity",
                "reason_code",
                "reason_note",
                "counted_by",
                "counted_at",
                "updated_at",
            ],
        )

    messages.success(request, f"{len(lines)} remaining SKU(s) marked the same as system stock.")
    return redirect("stock_count_detail", pk=session.pk)


# =========================================================
# REVIEW / CONFIRM / CANCEL
# =========================================================


@login_required
@require_POST
@transaction.atomic
def stock_count_submit(request, pk):
    if not _can_count_stock(request.user):
        messages.error(request, "Permission denied.")
        return redirect("item_list")

    session = _get_session_for_user(request, pk, for_update=True)
    if session.status != "draft":
        messages.error(request, "Only a draft count can be sent for review.")
        return redirect("stock_count_detail", pk=session.pk)

    uncounted = session.lines.filter(actual_quantity__isnull=True).count()
    if uncounted:
        messages.error(request, f"{uncounted} SKU(s) are still not counted.")
        return redirect("stock_count_detail", pk=session.pk)

    missing_reasons = (
        session.lines
        .filter(actual_quantity__isnull=False)
        .exclude(actual_quantity=F("system_quantity"))
        .filter(reason_code="", reason_note="")
        .count()
    )

    if missing_reasons:
        messages.error(
            request,
            f"Add a reason to {missing_reasons} different SKU(s) before review.",
        )
        return redirect("stock_count_detail", pk=session.pk)

    session.status = "review"
    session.submitted_by = request.user
    session.submitted_at = timezone.now()
    session.save(update_fields=["status", "submitted_by", "submitted_at", "updated_at"])

    messages.success(request, "Stock count sent for Owner/Admin confirmation.")
    return redirect("stock_count_detail", pk=session.pk)


@login_required
@require_POST
@transaction.atomic
def stock_count_confirm(request, pk):
    if not _can_confirm_stock_count(request.user):
        messages.error(request, "Only Owner/Admin can confirm stock adjustments.")
        return redirect("stock_count_detail", pk=pk)

    session = _get_session_for_user(request, pk, for_update=True)
    if session.status != "review":
        messages.error(request, "This stock count is not waiting for confirmation.")
        return redirect("stock_count_detail", pk=session.pk)

    lines = list(
        session.lines
        .select_for_update()
        .select_related("variant", "variant__item")
        .order_by("id")
    )

    if any(line.actual_quantity is None for line in lines):
        messages.error(request, "Some SKU(s) are still not counted.")
        return redirect("stock_count_detail", pk=session.pk)

    missing_reasons = [
        line for line in lines
        if line.difference != 0 and not line.reason_code and not (line.reason_note or "").strip()
    ]
    if missing_reasons:
        messages.error(request, "Every stock difference requires a reason.")
        return redirect("stock_count_detail", pk=session.pk)

    # Difference is applied to the current live stock. This preserves stock
    # movements that happened after the individual SKU was physically counted.
    for line in lines:
        difference = line.difference
        if difference == 0:
            continue

        stock, _created = BranchStock.objects.select_for_update().get_or_create(
            branch=session.branch,
            variant=line.variant,
            defaults={"quantity": 0},
        )
        current_qty = int(stock.quantity or 0)
        new_qty = current_qty + difference

        StockMovement.objects.create(
            branch=session.branch,
            item=line.variant.item,
            variant=line.variant,
            movement_type="adjust",
            quantity=new_qty,
            note=(
                f"Stock Count #{session.id} | {_reason_text(line)} | "
                f"Counted by {_display_user(line.counted_by)} | "
                f"Count snapshot {line.system_quantity} → actual {line.actual_quantity}"
            )[:255],
            created_by=request.user,
        )

        line.applied_before_quantity = current_qty
        line.applied_after_quantity = new_qty
        line.save(update_fields=[
            "applied_before_quantity",
            "applied_after_quantity",
            "updated_at",
        ])

    session.status = "confirmed"
    session.confirmed_by = request.user
    session.confirmed_at = timezone.now()
    session.save(update_fields=["status", "confirmed_by", "confirmed_at", "updated_at"])

    messages.success(request, "Stock count confirmed. Differences were added to stock history.")
    return redirect("stock_count_detail", pk=session.pk)


@login_required
@require_POST
@transaction.atomic
def stock_count_cancel(request, pk):
    session = _get_session_for_user(request, pk, for_update=True)

    if session.status == "confirmed":
        messages.error(request, "A confirmed stock count cannot be cancelled.")
        return redirect("stock_count_detail", pk=session.pk)

    if not (_can_confirm_stock_count(request.user) or session.created_by_id == request.user.id):
        messages.error(request, "You cannot cancel this stock count.")
        return redirect("stock_count_detail", pk=session.pk)

    session.status = "cancelled"
    session.save(update_fields=["status", "updated_at"])

    messages.warning(request, "Stock count cancelled. No stock quantity was changed.")
    return redirect("stock_count_detail", pk=session.pk)
