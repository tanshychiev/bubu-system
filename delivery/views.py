from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from .models import DeliveryOrder


@login_required
def delivery_list(request):
    deliveries = DeliveryOrder.objects.all().order_by("-id")
    return render(request, "delivery/delivery_list.html", {"deliveries": deliveries})


@login_required
def delivery_detail(request, pk):
    delivery = get_object_or_404(DeliveryOrder, pk=pk)
    return render(request, "delivery/delivery_detail.html", {"delivery": delivery})


@login_required
def delivery_create(request):
    if request.method == "POST":
        DeliveryOrder.objects.create(
            customer_name=request.POST.get("customer_name"),
            phone=request.POST.get("phone"),
            address=request.POST.get("address"),
            delivery_fee=request.POST.get("delivery_fee") or 0,
        )
        messages.success(request, "Delivery created")
        return redirect("delivery_list")

    return render(request, "delivery/delivery_form.html")


@login_required
def delivery_delete(request, pk):
    delivery = get_object_or_404(DeliveryOrder, pk=pk)

    if request.method == "POST":
        delivery.delete()
        messages.success(request, "Deleted")
        return redirect("delivery_list")

    return render(request, "delivery/delivery_confirm_delete.html", {"delivery": delivery})