from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date

from .forms import PetForm, PetSaleForm, PetWarrantyClaimForm
from .models import Pet, PetSale, PetVaccine


def _save_pet_vaccines(request, pet):
    pet.vaccines.all().delete()

    vaccine_nos = request.POST.getlist("vaccine_no[]")
    vaccine_names = request.POST.getlist("vaccine_name[]")
    vaccine_dates = request.POST.getlist("vaccine_date[]")
    next_dates = request.POST.getlist("next_recommended_date[]")
    notes = request.POST.getlist("vaccine_note[]")

    total = max(
        len(vaccine_nos),
        len(vaccine_names),
        len(vaccine_dates),
        len(next_dates),
        len(notes),
    )

    for i in range(total):
        vaccine_no = vaccine_nos[i] if i < len(vaccine_nos) else ""
        vaccine_name = vaccine_names[i] if i < len(vaccine_names) else ""
        vaccine_date = vaccine_dates[i] if i < len(vaccine_dates) else ""
        next_date = next_dates[i] if i < len(next_dates) else ""
        note = notes[i] if i < len(notes) else ""

        if not vaccine_name and not vaccine_date and not next_date and not note:
            continue

        try:
            vaccine_no_value = int(vaccine_no or i + 1)
        except ValueError:
            vaccine_no_value = i + 1

        PetVaccine.objects.create(
            pet=pet,
            vaccine_no=vaccine_no_value,
            vaccine_name=vaccine_name or "",
            vaccine_date=parse_date(vaccine_date) if vaccine_date else None,
            next_recommended_date=parse_date(next_date) if next_date else None,
            note=note or "",
            created_by=request.user,
        )


@login_required
def pet_list(request):
    pets = Pet.objects.all().order_by("-created_at")

    q = request.GET.get("q", "").strip()
    pet_type = request.GET.get("pet_type", "").strip()
    status = request.GET.get("status", "").strip()

    if q:
        pets = pets.filter(
            Q(breed__icontains=q)
            | Q(name__icontains=q)
            | Q(color__icontains=q)
            | Q(note__icontains=q)
        )

    if pet_type:
        pets = pets.filter(pet_type=pet_type)

    if status:
        pets = pets.filter(status=status)

    all_pets = Pet.objects.all()

    return render(request, "pets/pet_list.html", {
        "pets": pets,
        "in_stock_count": all_pets.filter(status="in_stock").count(),
        "reserved_count": all_pets.filter(status="reserved").count(),
        "sold_count": all_pets.filter(status="sold").count(),
        "preorder_count": all_pets.filter(status="preorder").count(),
        "sick_dead_count": all_pets.filter(status__in=["sick", "dead"]).count(),
    })


@login_required
def pet_create(request):
    if request.method == "POST":
        form = PetForm(request.POST, request.FILES)

        if form.is_valid():
            pet = form.save(commit=False)
            pet.created_by = request.user
            pet.save()

            _save_pet_vaccines(request, pet)

            messages.success(request, "Pet created successfully.")
            return redirect("pet_detail", pet.id)
    else:
        form = PetForm()

    return render(request, "pets/pet_form.html", {
        "form": form,
        "pet": None,
    })


@login_required
def pet_edit(request, pk):
    pet = get_object_or_404(Pet, pk=pk)

    if request.method == "POST":
        form = PetForm(request.POST, request.FILES, instance=pet)

        if form.is_valid():
            pet = form.save(commit=False)

            if request.POST.get("remove_photo") == "1" and pet.photo:
                pet.photo.delete(save=False)
                pet.photo = None

            pet.save()

            _save_pet_vaccines(request, pet)

            messages.success(request, "Pet updated successfully.")
            return redirect("pet_detail", pet.id)
    else:
        form = PetForm(instance=pet)

    return render(request, "pets/pet_form.html", {
        "form": form,
        "pet": pet,
    })


@login_required
def pet_detail(request, pk):
    pet = get_object_or_404(Pet, pk=pk)

    return render(request, "pets/pet_detail.html", {
        "pet": pet,
    })


@login_required
def pet_sale_create(request):
    selected_pet = None
    pet_id = request.GET.get("pet")

    if pet_id:
        selected_pet = Pet.objects.filter(pk=pet_id).first()

    if request.method == "POST":
        form = PetSaleForm(request.POST, request.FILES)

        if form.is_valid():
            sale = form.save(commit=False)
            sale.created_by = request.user

            if sale.sale_kind == "preorder":
                sale.pet = None

            sale.save()

            messages.success(request, "Pet sale saved successfully.")

            submit_action = request.POST.get("submit_action", "save")

            if submit_action == "save_print":
                return redirect("pet_sale_receipt_print", sale.id)

            if submit_action == "save_warranty":
                return redirect("pet_warranty_print", sale.id)

            return redirect("pet_sale_detail", sale.id)
    else:
        initial = {
            "sale_kind": "in_stock",
            "warranty_days": 3,
        }

        if selected_pet:
            initial.update({
                "pet": selected_pet,
                "sale_price": selected_pet.sale_price,
                "preorder_pet_type": selected_pet.pet_type,
                "preorder_breed": selected_pet.breed,
                "preorder_gender": selected_pet.gender,
            })

        form = PetSaleForm(initial=initial)

    pets = Pet.objects.filter(status__in=["in_stock", "preorder", "reserved"]).order_by("-created_at")

    return render(request, "pets/pet_sale_form.html", {
        "form": form,
        "pets": pets,
        "selected_pet": selected_pet,
        "sale": None,
    })


@login_required
def pet_sale_edit(request, pk):
    sale = get_object_or_404(PetSale, pk=pk)

    if request.method == "POST":
        form = PetSaleForm(request.POST, request.FILES, instance=sale)

        if form.is_valid():
            sale = form.save(commit=False)

            if sale.sale_kind == "preorder":
                sale.pet = None

            sale.save()

            messages.success(request, "Pet sale updated successfully.")
            return redirect("pet_sale_detail", sale.id)
    else:
        form = PetSaleForm(instance=sale)

    pets = Pet.objects.filter(
        Q(status__in=["in_stock", "preorder", "reserved"])
        | Q(pk=sale.pet_id)
    ).order_by("-created_at")

    return render(request, "pets/pet_sale_form.html", {
        "form": form,
        "pets": pets,
        "selected_pet": sale.pet,
        "sale": sale,
    })


@login_required
def pet_sale_detail(request, pk):
    sale = get_object_or_404(PetSale, pk=pk)

    return render(request, "pets/pet_sale_detail.html", {
        "sale": sale,
        "copy_text": sale.build_copy_text(),
    })


@login_required
def pet_sale_mark_arrived(request, pk):
    sale = get_object_or_404(PetSale, pk=pk)

    if request.method == "POST":
        sale.status = "arrived"
        sale.save(update_fields=["status"])
        messages.success(request, "Marked as arrived.")

    return redirect("pet_sale_detail", sale.id)


@login_required
def pet_sale_complete(request, pk):
    sale = get_object_or_404(PetSale, pk=pk)

    if request.method == "POST":
        extra_paid = request.POST.get("extra_paid") or "0"
        warranty_days = request.POST.get("warranty_days") or sale.warranty_days or 3

        try:
            sale.paid_amount = sale.paid_amount + sale.__class__._meta.get_field("paid_amount").to_python(extra_paid)
        except Exception:
            pass

        try:
            sale.warranty_days = int(warranty_days)
        except ValueError:
            sale.warranty_days = 3

        sale.status = "completed"
        sale.completed_at = timezone.now()
        sale.set_warranty_dates()
        sale.save()

        messages.success(request, "Pet sale completed. Warranty started.")

    return redirect("pet_sale_detail", sale.id)


@login_required
def pet_sale_cancel(request, pk):
    sale = get_object_or_404(PetSale, pk=pk)

    if request.method == "POST":
        sale.status = "cancelled"
        sale.cancel_reason = request.POST.get("cancel_reason", "")
        sale.save()

        messages.success(request, "Pet sale cancelled.")

    return redirect("pet_sale_detail", sale.id)


@login_required
def pet_sale_refund(request, pk):
    sale = get_object_or_404(PetSale, pk=pk)

    if request.method == "POST":
        sale.status = "refunded"
        sale.refund_reason = request.POST.get("refund_reason", "")
        sale.save()

        messages.success(request, "Pet sale refunded.")

    return redirect("pet_sale_detail", sale.id)


@login_required
def pet_warranty_print(request, pk):
    sale = get_object_or_404(PetSale, pk=pk)

    return render(request, "pets/warranty_print.html", {
        "sale": sale,
    })


@login_required
def pet_sale_receipt_print(request, pk):
    sale = get_object_or_404(PetSale, pk=pk)

    return render(request, "pets/pet_sale_receipt_print.html", {
        "sale": sale,
    })


@login_required
def pet_warranty_claim_create(request, sale_id):
    sale = get_object_or_404(PetSale, pk=sale_id)

    if request.method == "POST":
        form = PetWarrantyClaimForm(request.POST, request.FILES)

        if form.is_valid():
            claim = form.save(commit=False)
            claim.sale = sale
            claim.created_by = request.user
            claim.save()

            messages.success(request, "Warranty claim saved successfully.")
            return redirect("pet_sale_detail", sale.id)
    else:
        form = PetWarrantyClaimForm()

    return render(request, "pets/warranty_claim_form.html", {
        "form": form,
        "sale": sale,
    })