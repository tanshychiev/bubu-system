from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, F, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

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

    pending = (
        lines.filter(actual_quantity__isnull=False)
        .exclude(actual_quantity=F("system_quantity"))
        .count()
    )

    changed = (
        lines.filter(
            actual_quantity=F("system_quantity"),
            applied_before_quantity__isnull=False,
            applied_after_quantity__isnull=False,
        )
        .exclude(applied_before_quantity=F("applied_after_quantity"))
        .count()
    )

    correct = (
        lines.filter(actual_quantity=F("system_quantity"))
        .filter(
            Q(applied_before_quantity__isnull=True)
            | Q(applied_before_quantity=F("applied_after_quantity"))
        )
        .count()
    )

    return {
        "total": total,
        "counted": counted,
        "remaining": max(total - counted, 0),
        "pending": pending,
        "changed": changed,
        "correct": correct,
        # Backward-compatible name used by older templates/list code.
        "different": pending,
        "percent": round((counted / total) * 100) if total else 0,
    }


def _json_stats(session):
    return _session_stats(session)


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


def _line_history_rows(session, line, limit=20):
    return (
        StockMovement.objects
        .filter(
            branch=session.branch,
            variant=line.variant,
            movement_type="adjust",
            note__icontains="Stock Count #",
        )
        .select_related("created_by")
        .order_by("-created_at", "-id")[:limit]
    )


def _attach_last_confirmation(session, lines):
    """Attach the last completed count information without one query per line."""
    variant_ids = [line.variant_id for line in lines]
    if not variant_ids:
        return

    previous = (
        StockCountLine.objects
        .filter(
            session__branch=session.branch,
            session__status="confirmed",
            session__confirmed_at__isnull=False,
            variant_id__in=variant_ids,
        )
        .exclude(session=session)
        .select_related("session", "session__confirmed_by")
        .order_by("variant_id", "-session__confirmed_at", "-id")
    )

    latest_by_variant = {}
    for old_line in previous:
        latest_by_variant.setdefault(old_line.variant_id, old_line)

    for line in lines:
        old_line = latest_by_variant.get(line.variant_id)
        line.last_confirmed_at = old_line.session.confirmed_at if old_line else None
        line.last_confirmed_by = old_line.session.confirmed_by if old_line else None
        line.last_confirmed_before = old_line.applied_before_quantity if old_line else None
        line.last_confirmed_after = old_line.applied_after_quantity if old_line else None


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
            "can_confirm": _can_count_stock(request.user),
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

    lines = list(
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

    _attach_last_confirmation(session, lines)

    for line in lines:
        if line.actual_quantity is None:
            line.display_state = "uncounted"
        elif int(line.actual_quantity) != int(line.system_quantity or 0):
            line.display_state = "pending"
        elif (
            line.applied_before_quantity is not None
            and line.applied_after_quantity is not None
            and line.applied_before_quantity != line.applied_after_quantity
        ):
            line.display_state = "changed"
        else:
            line.display_state = "correct"

    stats = _session_stats(session)

    changed_lines = [
        line for line in lines
        if (
            line.applied_before_quantity is not None
            and line.applied_after_quantity is not None
            and line.applied_before_quantity != line.applied_after_quantity
        )
    ]

    return render(
        request,
        "inventory/stock_count_detail.html",
        {
            "session": session,
            "lines": lines,
            "stats": stats,
            "changed_lines": changed_lines,
            "reason_choices": StockCountLine.REASON_CHOICES,
            "can_confirm": _can_count_stock(request.user),
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

    if line.actual_quantity is None or force_recount:
        line.system_quantity = _get_current_quantity(session.branch, line.variant)

    line.actual_quantity = actual
    line.counted_by = request.user
    line.counted_at = timezone.now()

    difference = actual - int(line.system_quantity or 0)
    if difference == 0:
        # Correct items need no reason.
        line.reason_code = ""
        line.reason_note = ""

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
        "needs_change": difference != 0,
        "stats": _json_stats(session),
    })


@login_required
@require_POST
@transaction.atomic
def stock_count_apply_line(request, pk, line_id):
    """Apply one counted difference immediately and record permanent history."""
    if not _can_count_stock(request.user):
        return JsonResponse({"ok": False, "error": "Permission denied."}, status=403)

    session = _get_session_for_user(request, pk, for_update=True)
    if session.status not in ["draft", "review"]:
        return JsonResponse({"ok": False, "error": "This stock count is locked."}, status=400)

    line = get_object_or_404(
        StockCountLine.objects
        .select_for_update()
        .select_related("variant", "variant__item"),
        pk=line_id,
        session=session,
    )

    if line.actual_quantity is None:
        return JsonResponse({"ok": False, "error": "Enter the actual stock first."}, status=400)

    reason_code = (request.POST.get("reason_code") or "").strip()
    reason_note = (request.POST.get("reason_note") or "").strip()
    valid_reason_codes = {value for value, _label in StockCountLine.REASON_CHOICES}

    current_qty = _get_current_quantity(session.branch, line.variant)
    actual_qty = int(line.actual_quantity)

    if actual_qty != current_qty:
        if reason_code not in valid_reason_codes:
            return JsonResponse({"ok": False, "error": "Choose a reason for this change."}, status=400)
        if reason_code == "other" and not reason_note:
            return JsonResponse({"ok": False, "error": "Please explain the Other reason."}, status=400)

        line.reason_code = reason_code
        line.reason_note = reason_note

        movement = StockMovement.objects.create(
            branch=session.branch,
            item=line.variant.item,
            variant=line.variant,
            movement_type="adjust",
            quantity=actual_qty,
            note=(
                f"Stock Count #{session.id} | {_reason_text(line)} | "
                f"Changed by {_display_user(request.user)} | "
                f"System {current_qty} → actual {actual_qty}"
            )[:255],
            created_by=request.user,
        )

        before_qty = int(movement.before_quantity)
        after_qty = int(movement.after_quantity)
        changed = before_qty != after_qty
    else:
        before_qty = current_qty
        after_qty = current_qty
        changed = False
        line.reason_code = ""
        line.reason_note = ""

    # After applying, the system quantity becomes the new live stock. The line
    # therefore displays Correct, while applied_before/after preserve the change.
    line.applied_before_quantity = before_qty
    line.applied_after_quantity = after_qty
    line.system_quantity = after_qty
    line.actual_quantity = after_qty
    line.counted_by = request.user
    line.counted_at = timezone.now()
    line.save(update_fields=[
        "applied_before_quantity",
        "applied_after_quantity",
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
        "changed": changed,
        "before_quantity": before_qty,
        "after_quantity": after_qty,
        "system_quantity": line.system_quantity,
        "actual_quantity": line.actual_quantity,
        "difference": 0,
        "reason_label": line.get_reason_code_display() if line.reason_code else "",
        "reason_note": line.reason_note,
        "changed_by": _display_user(request.user),
        "changed_at": timezone.localtime(line.counted_at).strftime("%d %b %Y, %H:%M"),
        "stats": _json_stats(session),
    })


@login_required
@require_GET
def stock_count_line_history(request, pk, line_id):
    if not _can_count_stock(request.user):
        return JsonResponse({"ok": False, "error": "Permission denied."}, status=403)

    session = _get_session_for_user(request, pk)
    line = get_object_or_404(
        StockCountLine.objects.select_related("variant", "variant__item"),
        pk=line_id,
        session=session,
    )

    rows = []
    for movement in _line_history_rows(session, line):
        rows.append({
            "before": int(movement.before_quantity or 0),
            "after": int(movement.after_quantity or 0),
            "difference": int(movement.after_quantity or 0) - int(movement.before_quantity or 0),
            "by": _display_user(movement.created_by),
            "at": timezone.localtime(movement.created_at).strftime("%d %b %Y, %H:%M"),
            "note": movement.note or "",
        })

    return JsonResponse({"ok": True, "history": rows})


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

    messages.success(request, f"{len(lines)} remaining SKU(s) marked correct.")
    return redirect("stock_count_detail", pk=session.pk)


# =========================================================
# DIRECT FINISH / CANCEL
# =========================================================


def _finish_count(request, session):
    lines = list(
        session.lines
        .select_for_update()
        .select_related("variant")
        .order_by("id")
    )

    uncounted = [line for line in lines if line.actual_quantity is None]
    if uncounted:
        messages.error(request, f"{len(uncounted)} SKU(s) are still not counted.")
        return redirect("stock_count_detail", pk=session.pk)

    pending = []
    for line in lines:
        live_qty = _get_current_quantity(session.branch, line.variant)
        if int(line.actual_quantity) != live_qty:
            pending.append(line)

    if pending:
        messages.error(
            request,
            f"{len(pending)} SKU(s) still need Change Stock before finishing.",
        )
        return redirect("stock_count_detail", pk=session.pk)

    now = timezone.now()
    session.status = "confirmed"
    session.submitted_by = request.user
    session.submitted_at = now
    session.confirmed_by = request.user
    session.confirmed_at = now
    session.save(update_fields=[
        "status",
        "submitted_by",
        "submitted_at",
        "confirmed_by",
        "confirmed_at",
        "updated_at",
    ])

    messages.success(request, "Stock count finished and locked. The summary and history are saved.")
    return redirect("stock_count_detail", pk=session.pk)


@login_required
@require_POST
@transaction.atomic
def stock_count_submit(request, pk):
    """Backward-compatible URL: finish directly without a review stage."""
    if not _can_count_stock(request.user):
        messages.error(request, "Permission denied.")
        return redirect("item_list")

    session = _get_session_for_user(request, pk, for_update=True)
    if session.status not in ["draft", "review"]:
        messages.error(request, "This stock count is already locked.")
        return redirect("stock_count_detail", pk=session.pk)

    return _finish_count(request, session)


@login_required
@require_POST
@transaction.atomic
def stock_count_confirm(request, pk):
    """Finish directly. Kept under the old URL for existing links."""
    if not _can_count_stock(request.user):
        messages.error(request, "Permission denied.")
        return redirect("item_list")

    session = _get_session_for_user(request, pk, for_update=True)
    if session.status not in ["draft", "review"]:
        messages.error(request, "This stock count is already locked.")
        return redirect("stock_count_detail", pk=session.pk)

    return _finish_count(request, session)


@login_required
@require_POST
@transaction.atomic
def stock_count_cancel(request, pk):
    session = _get_session_for_user(request, pk, for_update=True)

    if session.status == "confirmed":
        messages.error(request, "A confirmed stock count cannot be cancelled.")
        return redirect("stock_count_detail", pk=session.pk)

    if not (_can_count_stock(request.user) and (is_owner(request.user) or session.created_by_id == request.user.id)):
        messages.error(request, "You cannot cancel this stock count.")
        return redirect("stock_count_detail", pk=session.pk)

    session.status = "cancelled"
    session.save(update_fields=["status", "updated_at"])

    messages.warning(request, "Stock count cancelled. Applied stock changes remain in permanent history.")
    return redirect("stock_count_detail", pk=session.pk)
