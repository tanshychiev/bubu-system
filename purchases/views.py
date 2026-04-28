from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.core.exceptions import ValidationError

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


@login_required
def purchase_list(request):
    purchases = Purchase.objects.prefetch_related("items").order_by("-id")

    total_purchases = purchases.count()
    total_spent = purchases.aggregate(total=Sum("total_amount"))["total"] or 0
    pending_orders = purchases.exclude(status="received").count()

    today = timezone.localdate()
    this_month = Purchase.objects.filter(
        created_at__year=today.year,
        created_at__month=today.month,
    ).aggregate(total=Sum("total_amount"))["total"] or 0

    return render(request, "purchases/purchase_list.html", {
        "purchases": purchases,
        "total_purchases": total_purchases,
        "total_spent": total_spent,
        "pending_orders": pending_orders,
        "this_month": this_month,
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
            return redirect("purchase_detail", pk=purchase.pk)

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
            return redirect("purchase_detail", pk=purchase.pk)

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
        PurchaseItem.objects.select_related("purchase", "variant", "variant__item"),
        pk=item_id,
    )

    if request.method == "POST":
        qty = _to_int(request.POST.get("qty"))
        note = request.POST.get("note", "").strip()

        if qty <= 0:
            messages.error(request, "Receive qty must be greater than 0.")
            return redirect("purchase_detail", pk=purchase_item.purchase.pk)

        if qty > purchase_item.pending_qty:
            messages.error(request, f"Cannot receive more than pending qty: {purchase_item.pending_qty}")
            return redirect("purchase_detail", pk=purchase_item.purchase.pk)

        PurchaseReceiveLog.objects.create(
            purchase_item=purchase_item,
            qty=qty,
            note=note,
            received_by=request.user,
        )

        purchase_item.purchase.refresh_status()

        messages.success(request, f"Supplier received {qty} pcs.")
        return redirect("purchase_detail", pk=purchase_item.purchase.pk)

    return redirect("purchase_detail", pk=purchase_item.purchase.pk)


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
            return redirect("purchase_detail", pk=purchase_item.purchase.pk)

        if qty <= 0:
            messages.error(request, "Qty must be greater than 0.")
            return redirect("purchase_detail", pk=purchase_item.purchase.pk)

        if qty > purchase_item.unallocated_qty:
            messages.error(request, f"Cannot allocate more than available qty: {purchase_item.unallocated_qty}")
            return redirect("purchase_detail", pk=purchase_item.purchase.pk)

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
        return redirect("purchase_detail", pk=purchase_item.purchase.pk)

    return redirect("purchase_detail", pk=purchase_item.purchase.pk)


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
            return redirect("purchase_detail", pk=purchase_item.purchase.pk)

        if from_branch_id == to_branch_id:
            messages.error(request, "From branch and to branch cannot be same.")
            return redirect("purchase_detail", pk=purchase_item.purchase.pk)

        if qty <= 0:
            messages.error(request, "Transfer qty must be greater than 0.")
            return redirect("purchase_detail", pk=purchase_item.purchase.pk)

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

            return redirect("purchase_detail", pk=purchase_item.purchase.pk)

        messages.success(
            request,
            f"Transfer created: {from_branch.name} → {to_branch.name}, {qty} pcs."
        )
        return redirect("purchase_detail", pk=purchase_item.purchase.pk)

    return redirect("purchase_detail", pk=purchase_item.purchase.pk)

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
            return redirect("purchase_detail", pk=transfer.purchase_item.purchase.pk)

        transfer.mark_received(user=request.user)
        messages.success(request, f"{transfer.qty} pcs received at {transfer.to_branch.name}.")

    return redirect("purchase_detail", pk=transfer.purchase_item.purchase.pk)


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