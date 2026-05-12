from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from .models import Delivery, DeliveryCompany
from .forms import DeliveryForm


def get_user_branch(user):
    profile = getattr(user, "staff_profile", None)

    if profile and profile.branch_id:
        return profile.branch

    return None


@login_required
def delivery_list(request):
    user_branch = get_user_branch(request.user)

    today = timezone.localdate()
    month_start = today.replace(day=1)

    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()

    if not date_from:
        date_from = month_start.isoformat()

    if not date_to:
        date_to = today.isoformat()

    deliveries = (
        Delivery.objects
        .select_related("branch", "sale", "delivery_company")
        .all()
        .order_by("-delivery_date", "-created_at")
    )

    if not request.user.is_superuser and user_branch:
        deliveries = deliveries.filter(branch=user_branch)

    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    payment_type = request.GET.get("payment_type", "").strip()

    if q:
        deliveries = deliveries.filter(
            Q(customer_name__icontains=q) |
            Q(phone__icontains=q) |
            Q(location__icontains=q) |
            Q(delivery_note__icontains=q) |
            Q(branch__name__icontains=q) |
            Q(delivery_company__name__icontains=q) |
            Q(sale__id__icontains=q)
        )

    if status:
        deliveries = deliveries.filter(status=status)

    if payment_type:
        deliveries = deliveries.filter(payment_type=payment_type)

    if date_from:
        deliveries = deliveries.filter(delivery_date__gte=date_from)

    if date_to:
        deliveries = deliveries.filter(delivery_date__lte=date_to)

    branches = None
    if request.user.is_superuser:
        from inventory.models import Branch
        branches = Branch.objects.filter(is_active=True).order_by("name")

    return render(request, "delivery/delivery_list.html", {
        "deliveries": deliveries,
        "current_branch": user_branch,
        "branches": branches,
        "date_from": date_from,
        "date_to": date_to,
    })


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
        initial = {}

        if not request.user.is_superuser and user_branch:
            initial["branch"] = user_branch

        form = DeliveryForm(initial=initial)

    return render(request, "delivery/delivery_form.html", {
        "form": form,
        "title": "Create Delivery",
        "current_branch": user_branch,
    })


@login_required
def delivery_update(request, pk):
    user_branch = get_user_branch(request.user)

    delivery = get_object_or_404(
        Delivery.objects.select_related("branch", "sale", "delivery_company"),
        pk=pk,
    )

    if not request.user.is_superuser and user_branch and delivery.branch_id != user_branch.id:
        messages.error(request, "You do not have permission to edit this delivery.")
        return redirect("delivery_list")

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

    return render(request, "delivery/delivery_form.html", {
        "form": form,
        "delivery": delivery,
        "title": "Edit Delivery",
        "current_branch": user_branch,
    })


@login_required
def delivery_detail(request, pk):
    user_branch = get_user_branch(request.user)

    delivery = get_object_or_404(
        Delivery.objects
        .select_related("branch", "sale", "delivery_company")
        .prefetch_related("items__variant", "items__variant__item"),
        pk=pk,
    )

    if not request.user.is_superuser and user_branch and delivery.branch_id != user_branch.id:
        messages.error(request, "You do not have permission to view this delivery.")
        return redirect("delivery_list")

    return render(request, "delivery/delivery_detail.html", {
        "delivery": delivery,
        "current_branch": user_branch,
    })


@login_required
def delivery_delete(request, pk):
    user_branch = get_user_branch(request.user)

    delivery = get_object_or_404(Delivery, pk=pk)

    if not request.user.is_superuser and user_branch and delivery.branch_id != user_branch.id:
        messages.error(request, "You do not have permission to delete this delivery.")
        return redirect("delivery_list")

    if request.method == "POST":
        delivery.delete()
        messages.success(request, "Delivery deleted successfully.")
        return redirect("delivery_list")

    return render(request, "delivery/delivery_confirm_delete.html", {
        "delivery": delivery,
        "current_branch": user_branch,
    })


@login_required
def delivery_sticker(request, pk):
    user_branch = get_user_branch(request.user)

    delivery = get_object_or_404(
        Delivery.objects.select_related("branch", "sale", "delivery_company"),
        pk=pk,
    )

    if not request.user.is_superuser and user_branch and delivery.branch_id != user_branch.id:
        messages.error(request, "You do not have permission to print this delivery.")
        return redirect("delivery_list")

    return render(request, "delivery/delivery_sticker.html", {
        "delivery": delivery,
        "current_branch": user_branch,
    })


@login_required
def delivery_company_create(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        delivery_type = request.POST.get("delivery_type", "").strip()
        phone = request.POST.get("phone", "").strip()
        note = request.POST.get("note", "").strip()
        is_active = request.POST.get("is_active") == "on"

        if not name:
            messages.error(request, "Please enter delivery company name.")
            return redirect("delivery_company_create")

        if delivery_type not in ["pp", "province"]:
            messages.error(request, "Please choose delivery type.")
            return redirect("delivery_company_create")

        DeliveryCompany.objects.create(
            name=name,
            delivery_type=delivery_type,
            phone=phone,
            note=note,
            is_active=is_active,
        )

        messages.success(request, "Delivery company created successfully.")
        return redirect("delivery_list")

    return render(request, "delivery/delivery_company_form.html")