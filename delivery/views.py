from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404

from .models import Delivery
from .forms import DeliveryForm


def get_user_branch(user):
    profile = getattr(user, "staff_profile", None)

    if profile and profile.branch_id:
        return profile.branch

    return None


@login_required
def delivery_list(request):
    user_branch = get_user_branch(request.user)

    deliveries = (
        Delivery.objects
        .select_related("branch", "sale")
        .all()
        .order_by("delivery_date", "-created_at")
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
            Q(sale__id__icontains=q)
        )

    if status:
        deliveries = deliveries.filter(status=status)

    if payment_type:
        deliveries = deliveries.filter(payment_type=payment_type)

    branches = None
    if request.user.is_superuser:
        from inventory.models import Branch
        branches = Branch.objects.filter(is_active=True).order_by("name")

    return render(request, "delivery/delivery_list.html", {
        "deliveries": deliveries,
        "current_branch": user_branch,
        "branches": branches,
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
        Delivery.objects.select_related("branch", "sale"),
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
        .select_related("branch", "sale")
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
        Delivery.objects.select_related("branch", "sale"),
        pk=pk,
    )

    if not request.user.is_superuser and user_branch and delivery.branch_id != user_branch.id:
        messages.error(request, "You do not have permission to print this delivery.")
        return redirect("delivery_list")

    return render(request, "delivery/delivery_sticker.html", {
        "delivery": delivery,
        "current_branch": user_branch,
    })