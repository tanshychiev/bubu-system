from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from customers.models import Customer
from inventory.models import Branch, StockMovement

from .forms import DeliveryCompanyForm, DeliveryForm
from .models import Delivery, DeliveryCompany


ZERO = Decimal("0.00")


def get_user_branch(user):
    profile = getattr(user, "staff_profile", None)
    if profile and profile.branch_id:
        return profile.branch
    return None


def _delivery_queryset(request):
    user_branch = get_user_branch(request.user)
    queryset = (
        Delivery.objects
        .select_related(
            "branch",
            "sale",
            "delivery_company",
            "cod_received_by",
            "cod_settled_by",
            "delivered_by",
            "returned_by",
        )
        .all()
    )

    if not request.user.is_superuser and user_branch:
        queryset = queryset.filter(branch=user_branch)

    return queryset


def _get_allowed_delivery(request, pk, for_update=False):
    queryset = _delivery_queryset(request)
    if for_update:
        queryset = queryset.select_for_update()
    return get_object_or_404(queryset, pk=pk)


def _decimal(value, default="0.00"):
    try:
        return Decimal(str(value if value not in (None, "") else default))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


@login_required
def delivery_list(request):
    today = timezone.localdate()
    month_start = today.replace(day=1)

    date_from = request.GET.get("date_from", "").strip() or month_start.isoformat()
    date_to = request.GET.get("date_to", "").strip() or today.isoformat()

    deliveries = _delivery_queryset(request).order_by("-delivery_date", "-created_at")

    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    payment_type = request.GET.get("payment_type", "").strip()
    delivery_area = request.GET.get("delivery_area", "").strip()
    company_id = request.GET.get("company", "").strip()
    branch_id = request.GET.get("branch", "").strip()
    cod_status = request.GET.get("cod_status", "").strip()

    if q:
        deliveries = deliveries.filter(
            Q(customer_name__icontains=q)
            | Q(social_name__icontains=q)
            | Q(phone__icontains=q)
            | Q(location__icontains=q)
            | Q(delivery_note__icontains=q)
            | Q(branch__name__icontains=q)
            | Q(delivery_company__name__icontains=q)
            | Q(sale__id__icontains=q)
        )

    if status:
        deliveries = deliveries.filter(status=status)
    if payment_type:
        deliveries = deliveries.filter(payment_type=payment_type)
    if delivery_area:
        deliveries = deliveries.filter(delivery_area=delivery_area)
    if company_id:
        deliveries = deliveries.filter(delivery_company_id=company_id)
    if branch_id and request.user.is_superuser:
        deliveries = deliveries.filter(branch_id=branch_id)
    if cod_status:
        deliveries = deliveries.filter(cod_status=cod_status)
    if date_from:
        deliveries = deliveries.filter(delivery_date__gte=date_from)
    if date_to:
        deliveries = deliveries.filter(delivery_date__lte=date_to)

    return render(
        request,
        "delivery/delivery_list.html",
        {
            "deliveries": deliveries,
            "current_branch": get_user_branch(request.user),
            "branches": Branch.objects.filter(is_active=True).order_by("name") if request.user.is_superuser else None,
            "delivery_companies": DeliveryCompany.objects.all().order_by("delivery_type", "name"),
            "date_from": date_from,
            "date_to": date_to,
            "selected_status": status,
            "selected_payment": payment_type,
            "selected_area": delivery_area,
            "selected_company": company_id,
            "selected_branch": branch_id,
            "selected_cod_status": cod_status,
        },
    )


@login_required
def delivery_create(request):
    user_branch = get_user_branch(request.user)

    if request.method == "POST":
        form = DeliveryForm(request.POST)
        if form.is_valid():
            delivery = form.save(commit=False)
            if not request.user.is_superuser:
                delivery.branch = user_branch
            delivery.save()
            messages.success(request, "Delivery created successfully.")
            return redirect("delivery_detail", pk=delivery.pk)
    else:
        initial = {"delivery_date": timezone.localdate(), "status": "pending"}
        if not request.user.is_superuser and user_branch:
            initial["branch"] = user_branch
        form = DeliveryForm(initial=initial)

    return render(
        request,
        "delivery/delivery_form.html",
        {
            "form": form,
            "title": "Create Delivery",
            "current_branch": user_branch,
        },
    )


@login_required
def delivery_update(request, pk):
    user_branch = get_user_branch(request.user)
    delivery = _get_allowed_delivery(request, pk)

    if request.method == "POST":
        form = DeliveryForm(request.POST, instance=delivery)
        if form.is_valid():
            delivery = form.save(commit=False)
            if not request.user.is_superuser:
                delivery.branch = user_branch
            delivery.save()
            messages.success(request, "Delivery updated successfully.")
            return redirect("delivery_detail", pk=delivery.pk)
    else:
        form = DeliveryForm(instance=delivery)

    return render(
        request,
        "delivery/delivery_form.html",
        {
            "form": form,
            "delivery": delivery,
            "title": "Edit Delivery",
            "current_branch": user_branch,
        },
    )


@login_required
def delivery_detail(request, pk):
    delivery = get_object_or_404(
        _delivery_queryset(request).prefetch_related(
            "items__variant",
            "items__variant__item",
            "sale__items__item",
            "sale__items__variant",
        ),
        pk=pk,
    )
    return render(
        request,
        "delivery/delivery_detail.html",
        {"delivery": delivery, "current_branch": get_user_branch(request.user)},
    )


@login_required
def delivery_delete(request, pk):
    delivery = _get_allowed_delivery(request, pk)

    if request.method == "POST":
        if delivery.return_stock_restored:
            messages.error(request, "Returned delivery records cannot be deleted after stock restoration.")
            return redirect("delivery_detail", pk=delivery.pk)
        delivery.delete()
        messages.success(request, "Delivery deleted successfully.")
        return redirect("delivery_list")

    return render(
        request,
        "delivery/delivery_confirm_delete.html",
        {"delivery": delivery, "current_branch": get_user_branch(request.user)},
    )


@login_required
def delivery_sticker(request, pk):
    delivery = _get_allowed_delivery(request, pk)
    return render(
        request,
        "delivery/delivery_sticker.html",
        {"delivery": delivery, "current_branch": get_user_branch(request.user)},
    )


@login_required
def delivery_mark_out(request, pk):
    if request.method != "POST":
        return redirect("delivery_detail", pk=pk)

    with transaction.atomic():
        delivery = _get_allowed_delivery(request, pk, for_update=True)
        if delivery.status in {"returned", "cancelled"}:
            messages.error(request, "This delivery cannot be sent out.")
        else:
            delivery.status = "out"
            delivery.save(update_fields=["status", "updated_at"])
            messages.success(request, "Delivery marked Out For Delivery.")

    return redirect("delivery_detail", pk=pk)


@login_required
def delivery_mark_done(request, pk):
    if request.method != "POST":
        return redirect("delivery_detail", pk=pk)

    with transaction.atomic():
        delivery = _get_allowed_delivery(request, pk, for_update=True)
        if delivery.status == "returned":
            messages.error(request, "Returned delivery cannot be marked delivered.")
        else:
            delivery.status = "done"
            delivery.delivered_at = timezone.now()
            delivery.delivered_by = request.user
            delivery.failure_reason = ""
            delivery.save(
                update_fields=[
                    "status",
                    "delivered_at",
                    "delivered_by",
                    "failure_reason",
                    "updated_at",
                ]
            )
            messages.success(request, "Delivery marked Delivered. COD money remains separate until confirmed.")

    return redirect("delivery_detail", pk=pk)


@login_required
def delivery_mark_failed(request, pk):
    if request.method != "POST":
        return redirect("delivery_detail", pk=pk)

    reason = request.POST.get("reason", "").strip()
    if not reason:
        messages.error(request, "Please enter the delivery failure reason.")
        return redirect("delivery_detail", pk=pk)

    with transaction.atomic():
        delivery = _get_allowed_delivery(request, pk, for_update=True)
        if delivery.status == "returned":
            messages.error(request, "This delivery is already returned.")
        else:
            delivery.status = "failed"
            delivery.failure_reason = reason
            delivery.save(update_fields=["status", "failure_reason", "updated_at"])
            messages.success(request, "Delivery marked Failed. Use Return + Restore Stock after goods arrive back.")

    return redirect("delivery_detail", pk=pk)


def _restore_delivery_stock(delivery, user):
    restored_lines = 0

    if delivery.sale_id:
        rows = delivery.sale.items.select_related("item", "variant", "branch").all()
        for row in rows:
            if not row.variant_id:
                continue

            branch = row.branch or delivery.branch or delivery.sale.branch
            if not branch:
                raise ValueError("Cannot restore stock because the sale has no branch.")

            StockMovement.objects.create(
                branch=branch,
                item=row.item,
                variant=row.variant,
                movement_type="in",
                quantity=row.quantity,
                cost_price=row.variant.cost_price or row.item.cost_price,
                note=f"Delivery return #DLV-{delivery.id:04d} / Sale #{delivery.sale_id}",
                created_by=user,
            )
            restored_lines += 1
    else:
        rows = delivery.items.select_related("variant", "variant__item").all()
        for row in rows:
            if not row.variant_id:
                continue
            if not delivery.branch_id:
                raise ValueError("Cannot restore stock because the delivery has no branch.")

            StockMovement.objects.create(
                branch=delivery.branch,
                item=row.variant.item,
                variant=row.variant,
                movement_type="in",
                quantity=row.qty,
                cost_price=row.variant.cost_price or row.variant.item.cost_price,
                note=f"Manual delivery return #DLV-{delivery.id:04d}",
                created_by=user,
            )
            restored_lines += 1

    return restored_lines


@login_required
def delivery_return_stock(request, pk):
    if request.method != "POST":
        return redirect("delivery_detail", pk=pk)

    reason = request.POST.get("return_reason", "").strip()
    if not reason:
        messages.error(request, "Please enter the return reason.")
        return redirect("delivery_detail", pk=pk)

    with transaction.atomic():
        delivery = _get_allowed_delivery(request, pk, for_update=True)

        if delivery.return_stock_restored:
            messages.error(request, "Stock was already restored for this delivery.")
            return redirect("delivery_detail", pk=pk)

        try:
            restored_lines = _restore_delivery_stock(delivery, request.user)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("delivery_detail", pk=pk)

        delivery.status = "returned"
        delivery.return_reason = reason
        delivery.return_stock_restored = True
        delivery.returned_at = timezone.now()
        delivery.returned_by = request.user
        delivery.save(
            update_fields=[
                "status",
                "return_reason",
                "return_stock_restored",
                "returned_at",
                "returned_by",
                "updated_at",
            ]
        )

    messages.success(
        request,
        f"Delivery returned. Stock restored for {restored_lines} product line(s).",
    )
    return redirect("delivery_detail", pk=pk)


@login_required
def delivery_cod_report(request):
    today = timezone.localdate()
    month_start = today.replace(day=1)
    date_from = request.GET.get("date_from", "").strip() or month_start.isoformat()
    date_to = request.GET.get("date_to", "").strip() or today.isoformat()
    company_id = request.GET.get("company", "").strip()
    branch_id = request.GET.get("branch", "").strip()
    delivery_area = request.GET.get("delivery_area", "").strip()
    cod_status = request.GET.get("cod_status", "").strip()

    deliveries = _delivery_queryset(request).filter(
        payment_type__in=["cod_collect", "cod_shop"]
    )

    if date_from:
        deliveries = deliveries.filter(delivery_date__gte=date_from)
    if date_to:
        deliveries = deliveries.filter(delivery_date__lte=date_to)
    if company_id:
        deliveries = deliveries.filter(delivery_company_id=company_id)
    if branch_id and request.user.is_superuser:
        deliveries = deliveries.filter(branch_id=branch_id)
    if delivery_area:
        deliveries = deliveries.filter(delivery_area=delivery_area)
    if cod_status:
        deliveries = deliveries.filter(cod_status=cod_status)

    deliveries = list(deliveries.order_by("delivery_company__name", "delivery_date", "id"))

    cod_total = sum((d.cod_total for d in deliveries), ZERO)
    fee_total = sum((d.delivery_fee or ZERO for d in deliveries), ZERO)
    expected_total = sum((d.expected_company_pay for d in deliveries), ZERO)
    received_total = sum((d.actual_received or ZERO for d in deliveries), ZERO)
    lack_total = sum((d.lack_amount or ZERO for d in deliveries), ZERO)

    return render(
        request,
        "delivery/delivery_cod_report.html",
        {
            "deliveries": deliveries,
            "delivery_companies": DeliveryCompany.objects.all().order_by("delivery_type", "name"),
            "branches": Branch.objects.filter(is_active=True).order_by("name") if request.user.is_superuser else None,
            "date_from": date_from,
            "date_to": date_to,
            "selected_company": company_id,
            "selected_branch": branch_id,
            "selected_area": delivery_area,
            "selected_cod_status": cod_status,
            "cod_total": cod_total,
            "fee_total": fee_total,
            "expected_total": expected_total,
            "received_total": received_total,
            "lack_total": lack_total,
        },
    )


@login_required
def delivery_confirm_cod(request, pk):
    if request.method != "POST":
        return redirect("delivery_cod_report")

    with transaction.atomic():
        delivery = _get_allowed_delivery(request, pk, for_update=True)

        if delivery.payment_type not in {"cod_collect", "cod_shop"}:
            messages.error(request, "This is not a COD delivery.")
            return redirect("delivery_detail", pk=pk)

        if delivery.status != "done":
            messages.error(request, "Mark the delivery as Delivered before confirming COD money.")
            return redirect("delivery_detail", pk=pk)

        received = _decimal(
            request.POST.get("actual_received"),
            str(delivery.expected_company_pay),
        )
        if received < ZERO:
            messages.error(request, "Received amount cannot be negative.")
            return redirect("delivery_detail", pk=pk)

        delivery.actual_received = received
        delivery.cod_note = request.POST.get("cod_note", "").strip()
        delivery.cod_received_at = timezone.now()
        delivery.cod_received_by = request.user
        delivery.cod_settled_at = None
        delivery.cod_settled_by = None
        # save() derives received/short/waiting and lack amount.
        delivery.cod_status = "waiting"
        delivery.save(
            update_fields=[
                "actual_received",
                "cod_note",
                "cod_received_at",
                "cod_received_by",
                "cod_settled_at",
                "cod_settled_by",
                "cod_status",
                "updated_at",
            ]
        )

    if delivery.cod_status == "short":
        messages.warning(
            request,
            f"COD received with ${delivery.lack_amount:.2f} short money.",
        )
    else:
        messages.success(request, "COD money confirmed as received.")

    next_url = request.POST.get("next", "").strip()
    return redirect(next_url or "delivery_detail", pk=pk) if not next_url else redirect(next_url)


@login_required
def delivery_settle_cod(request, pk):
    if request.method != "POST":
        return redirect("delivery_detail", pk=pk)

    with transaction.atomic():
        delivery = _get_allowed_delivery(request, pk, for_update=True)

        if delivery.cod_status not in {"received", "short"}:
            messages.error(request, "Confirm received money before settling this COD.")
        else:
            delivery.cod_status = "settled"
            delivery.cod_settled_at = timezone.now()
            delivery.cod_settled_by = request.user
            delivery.save(
                update_fields=[
                    "cod_status",
                    "cod_settled_at",
                    "cod_settled_by",
                    "updated_at",
                ]
            )
            messages.success(request, "COD record settled.")

    next_url = request.POST.get("next", "").strip()
    return redirect(next_url or "delivery_detail", pk=pk) if not next_url else redirect(next_url)


@login_required
def delivery_company_list(request):
    delivery_type = request.GET.get("delivery_type", "").strip()
    active = request.GET.get("active", "").strip()

    companies = DeliveryCompany.objects.all().order_by("delivery_type", "name")
    if delivery_type:
        companies = companies.filter(delivery_type=delivery_type)
    if active == "yes":
        companies = companies.filter(is_active=True)
    elif active == "no":
        companies = companies.filter(is_active=False)

    return render(
        request,
        "delivery/delivery_company_list.html",
        {
            "companies": companies,
            "selected_type": delivery_type,
            "selected_active": active,
        },
    )


@login_required
def delivery_company_create(request):
    if request.method == "POST":
        form = DeliveryCompanyForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Delivery company created successfully.")
            return redirect("delivery_company_list")
    else:
        form = DeliveryCompanyForm(initial={"is_active": True, "default_fee": "1.25"})

    return render(
        request,
        "delivery/delivery_company_form.html",
        {"form": form, "title": "Create Delivery Company"},
    )


@login_required
def delivery_company_update(request, pk):
    company = get_object_or_404(DeliveryCompany, pk=pk)

    if request.method == "POST":
        form = DeliveryCompanyForm(request.POST, instance=company)
        if form.is_valid():
            form.save()
            messages.success(request, "Delivery company updated successfully.")
            return redirect("delivery_company_list")
    else:
        form = DeliveryCompanyForm(instance=company)

    return render(
        request,
        "delivery/delivery_company_form.html",
        {"form": form, "company": company, "title": "Edit Delivery Company"},
    )


@login_required
def delivery_company_toggle(request, pk):
    if request.method != "POST":
        return redirect("delivery_company_list")

    company = get_object_or_404(DeliveryCompany, pk=pk)
    company.is_active = not company.is_active
    company.save(update_fields=["is_active", "updated_at"])

    state = "activated" if company.is_active else "deactivated"
    messages.success(request, f"{company.name} {state}.")
    return redirect("delivery_company_list")


@login_required
def delivery_customer_lookup(request):
    phone = request.GET.get("phone", "").strip()
    if not phone:
        return JsonResponse({"found": False})

    customer = Customer.objects.filter(phone=phone).order_by("id").first()
    if not customer:
        return JsonResponse({"found": False})

    return JsonResponse(
        {
            "found": True,
            "name": customer.name or "",
            "phone": customer.phone or "",
            "address": customer.address or "",
            "chat_source": getattr(customer, "customer_chat_source", "") or "",
            "social_name": getattr(customer, "customer_social_name", "") or "",
        }
    )
