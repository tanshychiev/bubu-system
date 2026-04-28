from decimal import Decimal

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Sum, Count
from django.utils import timezone

from .models import Customer, CustomerHistory


@login_required
def customer_list(request):
    q = request.GET.get("q", "").strip()

    customers = Customer.objects.all().order_by("-id")

    if q:
        customers = customers.filter(
            Q(name__icontains=q) |
            Q(phone__icontains=q) |
            Q(address__icontains=q) |
            Q(pet_name__icontains=q) |
            Q(pet_type__icontains=q)
        )

    now = timezone.now()
    total = Customer.objects.count()
    new_month = Customer.objects.filter(
        created_at__year=now.year,
        created_at__month=now.month,
    ).count()

    spent = Customer.objects.aggregate(total=Sum("total_spent"))["total"] or Decimal("0.00")

    return render(request, "customers/customer_list.html", {
        "customers": customers,
        "q": q,
        "total": total,
        "new_month": new_month,
        "orders": 0,
        "spent": spent,
    })


@login_required
def customer_detail(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    return render(request, "customers/customer_detail.html", {
        "customer": customer,
    })


@login_required
def customer_create(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        phone = request.POST.get("phone", "").strip()

        if not name:
            name = phone or "Walk-in customer"

        Customer.objects.create(
            name=name,
            phone=phone,
            address=request.POST.get("address", "").strip(),
            pet_name=request.POST.get("pet_name", "").strip(),
            pet_type=request.POST.get("pet_type", "").strip(),
        )

        messages.success(request, "Customer created")
        return redirect("customer_list")

    return render(request, "customers/customer_form.html", {
        "title": "Add Customer",
    })


@login_required
def customer_update(request, pk):
    customer = get_object_or_404(Customer, pk=pk)

    if request.method == "POST":

        fields = ["name", "phone", "address", "pet_name", "pet_type"]

        for field in fields:
            old = getattr(customer, field) or ""
            new = request.POST.get(field, "").strip()

            if old != new:
                CustomerHistory.objects.create(
                    customer=customer,
                    field_name=field,
                    old_value=old,
                    new_value=new,
                    changed_by=request.user,
                )

                setattr(customer, field, new)

        customer.updated_by = request.user
        customer.save()

        messages.success(request, "Customer updated")
        return redirect("customer_update", pk=customer.id)

    return render(request, "customers/customer_form.html", {
        "customer": customer,
        "title": "Edit Customer",
    })


@login_required
def customer_delete(request, pk):
    customer = get_object_or_404(Customer, pk=pk)

    if request.method == "POST":
        customer.delete()
        messages.success(request, "Customer deleted")
        return redirect("customer_list")

    return render(request, "customers/customer_confirm_delete.html", {
        "customer": customer,
    })