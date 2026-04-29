from django.contrib import messages
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404

from .models import Delivery
from .forms import DeliveryForm


def delivery_list(request):
    deliveries = Delivery.objects.all().order_by("delivery_date", "-created_at")

    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    payment_type = request.GET.get("payment_type", "").strip()

    if q:
        deliveries = deliveries.filter(
            Q(customer_name__icontains=q) |
            Q(phone__icontains=q) |
            Q(location__icontains=q) |
            Q(delivery_note__icontains=q)
        )

    if status:
        deliveries = deliveries.filter(status=status)

    if payment_type:
        deliveries = deliveries.filter(payment_type=payment_type)

    return render(request, "delivery/delivery_list.html", {
        "deliveries": deliveries,
    })


def delivery_create(request):
    if request.method == "POST":
        form = DeliveryForm(request.POST)
        if form.is_valid():
            delivery = form.save()
            messages.success(request, "Delivery created successfully.")
            return redirect("delivery_detail", pk=delivery.pk)
    else:
        form = DeliveryForm()

    return render(request, "delivery/delivery_form.html", {
        "form": form,
        "title": "Create Delivery",
    })


def delivery_update(request, pk):
    delivery = get_object_or_404(Delivery, pk=pk)

    if request.method == "POST":
        form = DeliveryForm(request.POST, instance=delivery)
        if form.is_valid():
            delivery = form.save()
            messages.success(request, "Delivery updated successfully.")
            return redirect("delivery_detail", pk=delivery.pk)
    else:
        form = DeliveryForm(instance=delivery)

    return render(request, "delivery/delivery_form.html", {
        "form": form,
        "delivery": delivery,
        "title": "Edit Delivery",
    })


def delivery_detail(request, pk):
    delivery = get_object_or_404(Delivery, pk=pk)

    return render(request, "delivery/delivery_detail.html", {
        "delivery": delivery,
    })


def delivery_delete(request, pk):
    delivery = get_object_or_404(Delivery, pk=pk)

    if request.method == "POST":
        delivery.delete()
        messages.success(request, "Delivery deleted successfully.")
        return redirect("delivery_list")

    return render(request, "delivery/delivery_confirm_delete.html", {
        "delivery": delivery,
    })


def delivery_sticker(request, pk):
    delivery = get_object_or_404(Delivery, pk=pk)

    return render(request, "delivery/delivery_sticker.html", {
        "delivery": delivery,
    })