from decimal import Decimal

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Sum
from django.utils import timezone

from .models import Customer, CustomerHistory, CustomerPet


@login_required
def customer_list(request):
    q = request.GET.get("q", "").strip()

    customers = (
        Customer.objects
        .prefetch_related("pets")
        .all()
        .order_by("-id")
    )

    if q:
        customers = customers.filter(
            Q(name__icontains=q)
            | Q(phone__icontains=q)
            | Q(address__icontains=q)
            | Q(pet_name__icontains=q)
            | Q(pet_type__icontains=q)
            | Q(pets__pet_name__icontains=q)
            | Q(pets__breed__icontains=q)
            | Q(pets__pet_type__icontains=q)
        ).distinct()

    now = timezone.now()

    total = Customer.objects.count()

    new_month = Customer.objects.filter(
        created_at__year=now.year,
        created_at__month=now.month,
    ).count()

    spent = Customer.objects.aggregate(
        total=Sum("total_spent")
    )["total"] or Decimal("0.00")

    total_pets = CustomerPet.objects.count()

    return render(request, "customers/customer_list.html", {
        "customers": customers,
        "q": q,
        "total": total,
        "new_month": new_month,
        "orders": 0,
        "spent": spent,
        "total_pets": total_pets,
    })


@login_required
def customer_detail(request, pk):
    customer = get_object_or_404(
        Customer.objects.prefetch_related(
            "pets",
            "histories",
        ),
        pk=pk,
    )

    customer_pets = customer.pets.all().order_by("-created_at")
    histories = customer.histories.all().order_by("-changed_at")

    return render(request, "customers/customer_detail.html", {
        "customer": customer,
        "customer_pets": customer_pets,
        "histories": histories,
    })


@login_required
def customer_create(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        phone = request.POST.get("phone", "").strip()

        if not name:
            name = phone or "Walk-in customer"

        customer = Customer.objects.create(
            name=name,
            phone=phone,
            email=request.POST.get("email", "").strip(),
            address=request.POST.get("address", "").strip(),
            pet_name=request.POST.get("pet_name", "").strip(),
            pet_type=request.POST.get("pet_type", "").strip(),
            created_by=request.user,
        )

        # Optional first own pet from customer form
        first_pet_name = request.POST.get("pet_name", "").strip()
        first_pet_type = request.POST.get("pet_type", "").strip()

        if first_pet_name or first_pet_type:
            CustomerPet.objects.create(
                customer=customer,
                pet_name=first_pet_name,
                pet_type=first_pet_type.lower() if first_pet_type else "dog",
                source="customer_own",
                created_by=request.user,
            )

        messages.success(request, "Customer created.")
        return redirect("customer_detail", pk=customer.id)

    return render(request, "customers/customer_form.html", {
        "title": "Add Customer",
    })


@login_required
def customer_update(request, pk):
    customer = get_object_or_404(Customer, pk=pk)

    if request.method == "POST":
        fields = [
            "name",
            "phone",
            "email",
            "address",
            "pet_name",
            "pet_type",
        ]

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

        messages.success(request, "Customer updated.")
        return redirect("customer_detail", pk=customer.id)

    return render(request, "customers/customer_form.html", {
        "customer": customer,
        "title": "Edit Customer",
    })


@login_required
def customer_delete(request, pk):
    customer = get_object_or_404(Customer, pk=pk)

    if request.method == "POST":
        customer.delete()
        messages.success(request, "Customer deleted.")
        return redirect("customer_list")

    return render(request, "customers/customer_confirm_delete.html", {
        "customer": customer,
    })


@login_required
def customer_pet_create(request, customer_id):
    customer = get_object_or_404(Customer, pk=customer_id)

    if request.method == "POST":
        CustomerPet.objects.create(
            customer=customer,
            photo=request.FILES.get("photo"),
            pet_name=request.POST.get("pet_name", "").strip(),
            pet_type=request.POST.get("pet_type", "dog").strip(),
            breed=request.POST.get("breed", "").strip(),
            gender=request.POST.get("gender", "").strip(),
            color=request.POST.get("color", "").strip(),
            birth_date=request.POST.get("birth_date") or None,
            age_text=request.POST.get("age_text", "").strip(),
            source=request.POST.get("source", "customer_own").strip(),
            bought_date=request.POST.get("bought_date") or None,
            warranty_start_date=request.POST.get("warranty_start_date") or None,
            warranty_expire_date=request.POST.get("warranty_expire_date") or None,
            note=request.POST.get("note", "").strip(),
            created_by=request.user,
        )

        messages.success(request, "Customer pet profile created.")
        return redirect("customer_detail", pk=customer.id)

    return render(request, "customers/customer_pet_form.html", {
        "customer": customer,
        "pet": None,
        "title": "Add Customer Pet",
    })


@login_required
def customer_pet_update(request, pk):
    pet = get_object_or_404(CustomerPet, pk=pk)
    customer = pet.customer

    if request.method == "POST":
        pet.pet_name = request.POST.get("pet_name", "").strip()
        pet.pet_type = request.POST.get("pet_type", "dog").strip()
        pet.breed = request.POST.get("breed", "").strip()
        pet.gender = request.POST.get("gender", "").strip()
        pet.color = request.POST.get("color", "").strip()
        pet.birth_date = request.POST.get("birth_date") or None
        pet.age_text = request.POST.get("age_text", "").strip()
        pet.source = request.POST.get("source", "customer_own").strip()
        pet.bought_date = request.POST.get("bought_date") or None
        pet.warranty_start_date = request.POST.get("warranty_start_date") or None
        pet.warranty_expire_date = request.POST.get("warranty_expire_date") or None
        pet.note = request.POST.get("note", "").strip()

        if request.FILES.get("photo"):
            pet.photo = request.FILES.get("photo")

        pet.save()

        messages.success(request, "Customer pet profile updated.")
        return redirect("customer_detail", pk=customer.id)

    return render(request, "customers/customer_pet_form.html", {
        "customer": customer,
        "pet": pet,
        "title": "Edit Customer Pet",
    })


@login_required
def customer_pet_delete(request, pk):
    pet = get_object_or_404(CustomerPet, pk=pk)
    customer = pet.customer

    if request.method == "POST":
        pet.delete()
        messages.success(request, "Customer pet profile deleted.")

    return redirect("customer_detail", pk=customer.id)