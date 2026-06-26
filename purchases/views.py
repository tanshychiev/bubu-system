from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.http import HttpResponseRedirect

from inventory.models import Branch

from .models import (
    Purchase,
    PurchaseItem,
    PurchaseReceiveLog,
    PurchaseBranchPlan,
    PurchaseBranchAllocation,
    BranchTransfer,
    PurchaseEditLog,
)
from .forms import PurchaseForm, PurchaseItemFormSet


def _to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def log_purchase_change(purchase, user, action, field_name="", old_value="", new_value=""):
    if str(old_value) == str(new_value):
        return

    PurchaseEditLog.objects.create(
        purchase=purchase,
        user=user,
        action=action,
        field_name=field_name,
        old_value=str(old_value or ""),
        new_value=str(new_value or ""),
    )


def _get_plan_rows(request, prefix):
    branch_ids = request.POST.getlist(f"{prefix}-plan_branch[]")
    qtys = request.POST.getlist(f"{prefix}-plan_qty[]")

    rows = []
    for branch_id, qty in zip(branch_ids, qtys):
        qty = _to_int(qty)
        if branch_id and qty > 0:
            rows.append((branch_id, qty))

    return rows


def _purchase_item_detail_url(purchase_item):
    """Return to the same product card after a receive/allocation action."""
    base_url = reverse(
        "purchase_detail",
        kwargs={"pk": purchase_item.purchase_id},
    )
    return f"{base_url}#item-{purchase_item.pk}"


def _redirect_to_purchase_item(purchase_item):
    return HttpResponseRedirect(_purchase_item_detail_url(purchase_item))


def _weighted_split(total_qty, plans):
    """
    Split an integer quantity by the saved shop-plan weights.

    Example:
        plan 50/50, actual received 105 -> 53/52
    """
    total_qty = max(int(total_qty or 0), 0)
    plans = list(plans)

    if total_qty <= 0 or not plans:
        return {}

    total_weight = sum(max(int(plan.qty or 0), 0) for plan in plans)
    if total_weight <= 0:
        return {}

    rows = []
    allocated = 0

    for index, plan in enumerate(plans):
        weight = max(int(plan.qty or 0), 0)
        numerator = total_qty * weight
        base_qty = numerator // total_weight
        remainder = numerator % total_weight

        rows.append({
            "plan": plan,
            "qty": base_qty,
            "remainder": remainder,
            "index": index,
        })
        allocated += base_qty

    leftover = total_qty - allocated

    # Largest-remainder method keeps the split proportional and deterministic.
    rows.sort(key=lambda row: (-row["remainder"], row["index"]))
    for row in rows[:leftover]:
        row["qty"] += 1

    return {
        row["plan"].branch_id: row["qty"]
        for row in rows
    }


def _allocate_all_unallocated_by_plan(purchase_item, user, note):
    """
    Send every currently unallocated received piece to shops using the plan ratio.

    It works for:
    - exact deliveries,
    - partial deliveries,
    - over-deliveries,
    - already-partially allocated items.
    """
    purchase_item.refresh_from_db(fields=["received_qty"])

    plans = list(
        purchase_item.branch_plans
        .select_related("branch")
        .order_by("id")
    )

    if not plans:
        raise ValidationError("No shop plan exists for this item.")

    if sum(plan.qty for plan in plans) <= 0:
        raise ValidationError("Shop plan quantity must be greater than 0.")

    unallocated_qty = purchase_item.unallocated_qty
    if unallocated_qty <= 0:
        return []

    current_by_branch = {
        row["branch"]: row["total"] or 0
        for row in (
            purchase_item.branch_allocations
            .values("branch")
            .annotate(total=Sum("qty"))
        )
    }

    target_by_branch = _weighted_split(
        purchase_item.received_qty,
        plans,
    )

    remaining_to_allocate = unallocated_qty
    allocations = []

    # First move each branch toward its proportional cumulative target.
    for plan in plans:
        current_qty = current_by_branch.get(plan.branch_id, 0)
        target_qty = target_by_branch.get(plan.branch_id, 0)
        needed_qty = max(target_qty - current_qty, 0)
        qty = min(needed_qty, remaining_to_allocate)

        if qty > 0:
            allocations.append((plan, qty))
            remaining_to_allocate -= qty

        if remaining_to_allocate <= 0:
            break

    # If earlier manual allocations made the current distribution uneven,
    # distribute any leftover again by the same shop-plan ratio.
    if remaining_to_allocate > 0:
        extra_split = _weighted_split(remaining_to_allocate, plans)
        for plan in plans:
            qty = extra_split.get(plan.branch_id, 0)
            if qty > 0:
                allocations.append((plan, qty))

    created = []
    for plan, qty in allocations:
        if qty <= 0:
            continue

        # The item may have been prefetched. Clear the relation cache so
        # PurchaseBranchAllocation.clean() always sees allocations created
        # earlier in this same transaction.
        purchase_item._prefetched_objects_cache.pop(
            "branch_allocations",
            None,
        )

        created.append(
            PurchaseBranchAllocation.objects.create(
                purchase_item=purchase_item,
                branch=plan.branch,
                qty=qty,
                allocated_by=user,
                note=note,
            )
        )

    purchase_item._prefetched_objects_cache.pop(
        "branch_allocations",
        None,
    )
    return created


@login_required
def purchase_list(request):
    from datetime import datetime, time

    today = timezone.localdate()

    # Default:
    # From = empty = all old purchases
    # To = today
    # Status = ordered + partial received
    date_from = request.GET.get("date_from") or ""
    date_to = request.GET.get("date_to") or today.strftime("%Y-%m-%d")
    status_filter = request.GET.get("status") or "active"

    purchases = Purchase.objects.prefetch_related("items").order_by("-id")

    # =========================
    # DATE FILTER
    # =========================
    # If date_from is empty, it means "All dates before date_to"
    if date_from:
        try:
            from_date = datetime.strptime(date_from, "%Y-%m-%d").date()
            from_datetime = timezone.make_aware(
                datetime.combine(from_date, time.min)
            )
            purchases = purchases.filter(created_at__gte=from_datetime)
        except ValueError:
            messages.warning(request, "Invalid from date. Showing without from-date filter.")
            date_from = ""

    if date_to:
        try:
            to_date = datetime.strptime(date_to, "%Y-%m-%d").date()
            to_datetime = timezone.make_aware(
                datetime.combine(to_date, time.max)
            )
            purchases = purchases.filter(created_at__lte=to_datetime)
        except ValueError:
            messages.warning(request, "Invalid to date. Showing until today.")
            date_to = today.strftime("%Y-%m-%d")
            to_datetime = timezone.make_aware(
                datetime.combine(today, time.max)
            )
            purchases = purchases.filter(created_at__lte=to_datetime)

    # =========================
    # STATUS FILTER
    # =========================
    # active   = Ordered + Partial Received
    # all      = All
    # complete = Fully Received
    # ordered  = Ordered only
    # partial  = Partial Received only
    if status_filter == "all":
        pass

    elif status_filter == "complete":
        purchases = purchases.filter(status="received")

    elif status_filter == "ordered":
        purchases = purchases.filter(status="ordered")

    elif status_filter == "partial":
        purchases = purchases.filter(status="partial")

    else:
        status_filter = "active"
        purchases = purchases.filter(status__in=["ordered", "partial"])

    filtered_purchases = purchases

    # =========================
    # SUMMARY BASED ON FILTER
    # =========================
    total_purchases = filtered_purchases.count()

    total_spent = (
        filtered_purchases.aggregate(total=Sum("total_amount"))["total"]
        or 0
    )

    pending_orders = filtered_purchases.filter(
        status__in=["ordered", "partial"]
    ).count()

    # This Month total, separate from current filter
    month_start = today.replace(day=1)

    this_month = (
        Purchase.objects.filter(
            created_at__date__gte=month_start,
            created_at__date__lte=today,
        ).aggregate(total=Sum("total_amount"))["total"]
        or 0
    )

    return render(request, "purchases/purchase_list.html", {
        "purchases": filtered_purchases,
        "total_purchases": total_purchases,
        "total_spent": total_spent,
        "pending_orders": pending_orders,
        "this_month": this_month,

        # Send filter values back to HTML
        "date_from": date_from,
        "date_to": date_to,
        "status_filter": status_filter,
    })


@login_required
def purchase_detail(request, pk):
    purchase = get_object_or_404(
        Purchase.objects.prefetch_related(
            "items__variant__item",
            "items__receive_logs",
            "items__branch_plans__branch",
            "items__branch_allocations__branch",
            "items__branch_transfers__from_branch",
            "items__branch_transfers__to_branch",
            "edit_logs__user",
        ),
        pk=pk,
    )

    branches = Branch.objects.filter(is_active=True).order_by("name")

    return render(request, "purchases/purchase_detail.html", {
        "purchase": purchase,
        "branches": branches,
    })


@login_required
@transaction.atomic
def purchase_create(request):
    purchase = Purchase()
    branches = Branch.objects.filter(is_active=True).order_by("name")

    if request.method == "POST":
        form = PurchaseForm(request.POST, instance=purchase)
        formset = PurchaseItemFormSet(request.POST, instance=purchase)

        if form.is_valid() and formset.is_valid():
            for item_form in formset.forms:
                if item_form.cleaned_data.get("DELETE"):
                    continue

                variant = item_form.cleaned_data.get("variant")
                ordered_qty = item_form.cleaned_data.get("ordered_qty") or 0

                if not variant:
                    continue

                plan_rows = _get_plan_rows(request, item_form.prefix)
                plan_total = sum(qty for branch_id, qty in plan_rows)

                if plan_total > ordered_qty:
                    messages.error(request, "Plan qty cannot be more than item qty.")
                    return render(request, "purchases/purchase_form.html", {
                        "form": form,
                        "formset": formset,
                        "branches": branches,
                        "title": "Create Purchase",
                    })

            purchase = form.save()
            formset.instance = purchase

            for item_form in formset.forms:
                if item_form.cleaned_data.get("DELETE"):
                    continue

                item = item_form.save(commit=False)

                if not item.variant:
                    continue

                item.purchase = purchase

                if not item.note:
                    item.note = "No plan"

                item.save()

                for branch_id, qty in _get_plan_rows(request, item_form.prefix):
                    PurchaseBranchPlan.objects.create(
                        purchase_item=item,
                        branch_id=branch_id,
                        qty=qty,
                    )

            purchase.refresh_status()
            messages.success(request, "Purchase created.")
            return redirect("purchase_list")

        messages.error(request, "Purchase create failed. Please check item rows.")

    else:
        form = PurchaseForm(instance=purchase)
        formset = PurchaseItemFormSet(
            instance=purchase,
            queryset=PurchaseItem.objects.none(),
            initial=[{}],
        )

    return render(request, "purchases/purchase_form.html", {
        "form": form,
        "formset": formset,
        "branches": branches,
        "title": "Create Purchase",
    })


@login_required
@transaction.atomic
def purchase_update(request, pk):
    purchase = get_object_or_404(Purchase, pk=pk)
    branches = Branch.objects.filter(is_active=True).order_by("name")

    old_purchase = Purchase.objects.get(pk=pk)

    old_items = {}
    for old_item in purchase.items.prefetch_related("branch_plans__branch").all():
        old_items[old_item.pk] = {
            "variant": str(old_item.variant) if old_item.variant else "",
            "ordered_qty": old_item.ordered_qty,
            "cost_price": old_item.cost_price,
            "note": old_item.note,
            "plans": ", ".join(
                f"{p.branch.name}: {p.qty}" for p in old_item.branch_plans.all()
            ),
            "label": str(old_item),
        }

    if request.method == "POST":
        form = PurchaseForm(request.POST, instance=purchase)
        formset = PurchaseItemFormSet(request.POST, instance=purchase)

        if form.is_valid() and formset.is_valid():
            for item_form in formset.forms:
                if item_form.cleaned_data.get("DELETE"):
                    continue

                variant = item_form.cleaned_data.get("variant")
                ordered_qty = item_form.cleaned_data.get("ordered_qty") or 0

                if not variant:
                    continue

                plan_rows = _get_plan_rows(request, item_form.prefix)
                plan_total = sum(qty for branch_id, qty in plan_rows)

                if plan_total > ordered_qty:
                    messages.error(request, "Plan qty cannot be more than item qty.")
                    return render(request, "purchases/purchase_form.html", {
                        "form": form,
                        "formset": formset,
                        "branches": branches,
                        "title": "Edit Purchase",
                        "purchase": purchase,
                    })

            purchase = form.save()

            log_purchase_change(purchase, request.user, "Edit Purchase", "supplier", old_purchase.supplier, purchase.supplier)
            log_purchase_change(purchase, request.user, "Edit Purchase", "total_amount", old_purchase.total_amount, purchase.total_amount)
            log_purchase_change(purchase, request.user, "Edit Purchase", "shipping_note", old_purchase.shipping_note, purchase.shipping_note)
            log_purchase_change(purchase, request.user, "Edit Purchase", "note", old_purchase.note, purchase.note)

            formset.instance = purchase

            for item_form in formset.forms:
                if item_form.cleaned_data.get("DELETE"):
                    if item_form.instance.pk:
                        old = old_items.get(item_form.instance.pk)
                        log_purchase_change(
                            purchase,
                            request.user,
                            "Delete Item",
                            "item",
                            old["label"] if old else item_form.instance,
                            "",
                        )
                        item_form.instance.delete()
                    continue

                item = item_form.save(commit=False)

                if not item.variant:
                    continue

                is_new = item.pk is None
                old = old_items.get(item.pk)

                item.purchase = purchase

                if not item.note:
                    item.note = "No plan"

                item.save()

                if is_new:
                    log_purchase_change(purchase, request.user, "Add Item", "item", "", item)
                elif old:
                    log_purchase_change(purchase, request.user, "Edit Item", "variant", old["variant"], item.variant)
                    log_purchase_change(purchase, request.user, "Edit Item", "ordered_qty", old["ordered_qty"], item.ordered_qty)
                    log_purchase_change(purchase, request.user, "Edit Item", "cost_price", old["cost_price"], item.cost_price)
                    log_purchase_change(purchase, request.user, "Edit Item", "note", old["note"], item.note)

                old_plan_text = old["plans"] if old else ""

                item.branch_plans.all().delete()

                for branch_id, qty in _get_plan_rows(request, item_form.prefix):
                    PurchaseBranchPlan.objects.create(
                        purchase_item=item,
                        branch_id=branch_id,
                        qty=qty,
                    )

                new_plan_text = ", ".join(
                    f"{p.branch.name}: {p.qty}"
                    for p in item.branch_plans.select_related("branch").all()
                )

                log_purchase_change(
                    purchase,
                    request.user,
                    "Edit Plan",
                    "shop_plan",
                    old_plan_text,
                    new_plan_text,
                )

            purchase.refresh_status()
            messages.success(request, "Purchase updated.")
            return redirect("purchase_list")

        messages.error(request, "Purchase update failed. Please check item rows.")

    else:
        form = PurchaseForm(instance=purchase)
        formset = PurchaseItemFormSet(instance=purchase)

    return render(request, "purchases/purchase_form.html", {
        "form": form,
        "formset": formset,
        "branches": branches,
        "title": "Edit Purchase",
        "purchase": purchase,
    })


@login_required
@transaction.atomic
def purchase_receive(request, item_id):
    purchase_item = get_object_or_404(
        PurchaseItem.objects.select_related(
            "purchase",
            "variant",
            "variant__item",
        ).prefetch_related(
            "branch_plans__branch",
            "branch_allocations",
        ),
        pk=item_id,
    )

    if request.method != "POST":
        return _redirect_to_purchase_item(purchase_item)

    follow_plan = request.POST.get("follow_plan") == "1"
    receive_with_shop_qty = (
        request.POST.get("receive_with_shop_qty") == "1"
    )
    note = request.POST.get("note", "").strip()

    plans = list(
        purchase_item.branch_plans
        .select_related("branch")
        .order_by("id")
    )
    planned_qty = sum(plan.qty for plan in plans)

    # Most-used action:
    # receive exactly what is still expected, then send all available stock
    # to shops according to the saved plan.
    if follow_plan:
        if not plans:
            messages.error(
                request,
                "No shop plan exists. Edit the purchase plan first.",
            )
            return _redirect_to_purchase_item(purchase_item)

        if planned_qty != purchase_item.ordered_qty:
            messages.error(
                request,
                (
                    f"Shop plan is {planned_qty}, but ordered quantity is "
                    f"{purchase_item.ordered_qty}. Edit the plan first."
                ),
            )
            return _redirect_to_purchase_item(purchase_item)

        qty_to_receive = purchase_item.pending_qty

        if qty_to_receive > 0:
            PurchaseReceiveLog.objects.create(
                purchase_item=purchase_item,
                qty=qty_to_receive,
                note=note or "Confirmed correct quantity",
                received_by=request.user,
            )

        purchase_item.refresh_from_db(fields=["received_qty"])

        try:
            allocations = _allocate_all_unallocated_by_plan(
                purchase_item,
                request.user,
                "Auto sent to shop by purchase plan",
            )
        except ValidationError as error:
            messages.error(request, "; ".join(error.messages))
            return _redirect_to_purchase_item(purchase_item)

        purchase_item.purchase.refresh_status()

        allocated_qty = sum(allocation.qty for allocation in allocations)
        if qty_to_receive > 0 or allocated_qty > 0:
            messages.success(
                request,
                (
                    f"Confirmed {qty_to_receive} received and sent "
                    f"{allocated_qty} pcs to shops by plan."
                ),
            )
        else:
            messages.info(request, "This item was already completed.")

        return _redirect_to_purchase_item(purchase_item)

    # Actual supplier count is different.
    # Staff enters exactly how many pieces go to each planned shop.
    if receive_with_shop_qty:
        qty = _to_int(request.POST.get("qty"))

        if qty <= 0:
            messages.error(
                request,
                "Actual received quantity must be greater than 0.",
            )
            return _redirect_to_purchase_item(purchase_item)

        if not plans:
            messages.error(
                request,
                "No shop plan exists. Edit the purchase plan first.",
            )
            return _redirect_to_purchase_item(purchase_item)

        branch_ids = request.POST.getlist("shop_branch[]")
        shop_qtys = request.POST.getlist("shop_qty[]")

        if len(branch_ids) != len(shop_qtys):
            messages.error(request, "Shop quantities are incomplete.")
            return _redirect_to_purchase_item(purchase_item)

        allowed_plans = {
            str(plan.branch_id): plan
            for plan in plans
        }

        requested_rows = []
        used_branch_ids = set()
        shop_total = 0

        for branch_id, raw_shop_qty in zip(branch_ids, shop_qtys):
            if branch_id not in allowed_plans:
                messages.error(request, "Invalid shop selected.")
                return _redirect_to_purchase_item(purchase_item)

            if branch_id in used_branch_ids:
                messages.error(request, "The same shop cannot be entered twice.")
                return _redirect_to_purchase_item(purchase_item)

            used_branch_ids.add(branch_id)
            shop_qty = _to_int(raw_shop_qty, default=-1)

            if shop_qty < 0:
                messages.error(
                    request,
                    "Shop quantity cannot be negative.",
                )
                return _redirect_to_purchase_item(purchase_item)

            requested_rows.append(
                (allowed_plans[branch_id], shop_qty)
            )
            shop_total += shop_qty

        if shop_total != qty:
            messages.error(
                request,
                (
                    f"Shop total must equal received quantity. "
                    f"Received: {qty}, shop total: {shop_total}."
                ),
            )
            return _redirect_to_purchase_item(purchase_item)

        try:
            # Nested atomic block ensures the receiving log is rolled back
            # if any shop allocation unexpectedly fails.
            with transaction.atomic():
                PurchaseReceiveLog.objects.create(
                    purchase_item=purchase_item,
                    qty=qty,
                    note=note or "Actual supplier count",
                    received_by=request.user,
                )

                purchase_item.refresh_from_db(fields=["received_qty"])
                purchase_item._prefetched_objects_cache.pop(
                    "branch_allocations",
                    None,
                )

                allocated_qty = 0

                for plan, shop_qty in requested_rows:
                    if shop_qty <= 0:
                        continue

                    purchase_item._prefetched_objects_cache.pop(
                        "branch_allocations",
                        None,
                    )

                    PurchaseBranchAllocation.objects.create(
                        purchase_item=purchase_item,
                        branch=plan.branch,
                        qty=shop_qty,
                        allocated_by=request.user,
                        note=(
                            note
                            or "Added from actual supplier count"
                        ),
                    )
                    allocated_qty += shop_qty

        except ValidationError as error:
            messages.error(request, "; ".join(error.messages))
            return _redirect_to_purchase_item(purchase_item)

        purchase_item.refresh_from_db(fields=["received_qty"])
        purchase_item.purchase.refresh_status()

        success_text = (
            f"Received {qty} pcs and added {allocated_qty} pcs to shops."
        )

        if purchase_item.extra_received_qty > 0:
            success_text += (
                f" Extra received: {purchase_item.extra_received_qty} pcs."
            )

        messages.success(request, success_text)
        return _redirect_to_purchase_item(purchase_item)

    # Legacy/manual receive action. It also permits over-delivery, but does
    # not allocate automatically. The redesigned detail page uses one of
    # the two actions above.
    qty = _to_int(request.POST.get("qty"))
    if qty <= 0:
        messages.error(request, "Receive qty must be greater than 0.")
        return _redirect_to_purchase_item(purchase_item)

    PurchaseReceiveLog.objects.create(
        purchase_item=purchase_item,
        qty=qty,
        note=note,
        received_by=request.user,
    )

    purchase_item.purchase.refresh_status()
    messages.success(
        request,
        f"Supplier received {qty} pcs. Stock still needs shop allocation.",
    )
    return _redirect_to_purchase_item(purchase_item)


@login_required
@transaction.atomic
def purchase_allocate(request, item_id):
    purchase_item = get_object_or_404(
        PurchaseItem.objects.select_related("purchase", "variant", "variant__item"),
        pk=item_id,
    )

    if request.method == "POST":
        branch_id = request.POST.get("branch")
        qty = _to_int(request.POST.get("qty"))
        note = request.POST.get("note", "").strip()

        if not branch_id:
            messages.error(request, "Please choose branch.")
            return _redirect_to_purchase_item(purchase_item)

        if qty <= 0:
            messages.error(request, "Qty must be greater than 0.")
            return _redirect_to_purchase_item(purchase_item)

        if qty > purchase_item.unallocated_qty:
            messages.error(request, f"Cannot allocate more than available qty: {purchase_item.unallocated_qty}")
            return _redirect_to_purchase_item(purchase_item)

        branch = get_object_or_404(Branch, pk=branch_id)

        PurchaseBranchAllocation.objects.create(
            purchase_item=purchase_item,
            branch=branch,
            qty=qty,
            allocated_by=request.user,
            note=note,
        )

        purchase_item.purchase.refresh_status()

        messages.success(request, f"Allocated {qty} pcs to {branch.name}.")
        return _redirect_to_purchase_item(purchase_item)

    return _redirect_to_purchase_item(purchase_item)


@login_required
@transaction.atomic
def purchase_transfer_create(request, item_id):
    purchase_item = get_object_or_404(
        PurchaseItem.objects.select_related("purchase", "variant", "variant__item"),
        pk=item_id,
    )

    if request.method == "POST":
        from_branch_id = request.POST.get("from_branch")
        to_branch_id = request.POST.get("to_branch")
        qty = _to_int(request.POST.get("qty"))
        note = request.POST.get("note", "").strip()

        if not from_branch_id or not to_branch_id:
            messages.error(request, "Please choose from branch and to branch.")
            return _redirect_to_purchase_item(purchase_item)

        if from_branch_id == to_branch_id:
            messages.error(request, "From branch and to branch cannot be same.")
            return _redirect_to_purchase_item(purchase_item)

        if qty <= 0:
            messages.error(request, "Transfer qty must be greater than 0.")
            return _redirect_to_purchase_item(purchase_item)

        from_branch = get_object_or_404(Branch, pk=from_branch_id)
        to_branch = get_object_or_404(Branch, pk=to_branch_id)

        try:
            transfer = BranchTransfer(
                purchase_item=purchase_item,
                from_branch=from_branch,
                to_branch=to_branch,
                qty=qty,
                sent_by=request.user,
                note=note,
            )
            transfer.full_clean()
            transfer.save()

        except ValidationError as e:
            if hasattr(e, "message_dict"):
                for field, errors in e.message_dict.items():
                    for error in errors:
                        messages.error(request, error)
            else:
                for error in e.messages:
                    messages.error(request, error)

            return _redirect_to_purchase_item(purchase_item)

        messages.success(
            request,
            f"Transfer created: {from_branch.name} → {to_branch.name}, {qty} pcs."
        )
        return _redirect_to_purchase_item(purchase_item)

    return _redirect_to_purchase_item(purchase_item)

@login_required
@transaction.atomic
def purchase_transfer_receive(request, transfer_id):
    transfer = get_object_or_404(
        BranchTransfer.objects.select_related(
            "purchase_item",
            "purchase_item__purchase",
            "from_branch",
            "to_branch",
        ),
        pk=transfer_id,
    )

    if request.method == "POST":
        if transfer.status != "pending":
            messages.warning(request, "This transfer is already received.")
            return _redirect_to_purchase_item(transfer.purchase_item)

        transfer.mark_received(user=request.user)
        messages.success(request, f"{transfer.qty} pcs received at {transfer.to_branch.name}.")

    return _redirect_to_purchase_item(transfer.purchase_item)


@login_required
def purchase_delete(request, pk):
    purchase = get_object_or_404(Purchase, pk=pk)

    if request.method == "POST":
        purchase.delete()
        messages.success(request, "Purchase deleted.")
        return redirect("purchase_list")

    return render(request, "purchases/purchase_confirm_delete.html", {
        "purchase": purchase,
    })