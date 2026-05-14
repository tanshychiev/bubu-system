from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date

from core.telegram import send_telegram_message, send_telegram_photos
from customers.models import Customer, CustomerPet, CustomerHistory

from .forms import PetForm, PetBreedForm, PetSaleForm, PetWarrantyClaimForm
from .models import Pet, PetBreed, PetSale, PetVaccine, PetSalePhoto


# =========================================================
# SMALL HELPERS
# =========================================================

def _to_decimal(value, default="0.00"):
    try:
        return Decimal(str(value or default))
    except Exception:
        return Decimal(default)


def _get_active_sellers():
    return User.objects.filter(is_active=True).order_by("username")


def _display_user(user):
    if user:
        return user.get_full_name() or user.username
    return "-"


def money_text(value):
    try:
        return f"${Decimal(value or 0):,.2f}"
    except Exception:
        return "$0.00"


def date_text(value):
    if not value:
        return "-"

    try:
        return value.strftime("%d/%m/%Y")
    except Exception:
        return str(value)


def _save_pet_sale_photos(request, sale):
    photos = request.FILES.getlist("sale_photos")

    for photo in photos:
        PetSalePhoto.objects.create(
            sale=sale,
            photo=photo,
        )


def _get_sale_first_photo(sale):
    first_sale_photo = sale.photos.first()

    if first_sale_photo and first_sale_photo.photo:
        return first_sale_photo.photo

    if sale.sale_photo:
        return sale.sale_photo

    if sale.pet and sale.pet.photo:
        return sale.pet.photo

    if sale.pet and sale.pet.breed_profile and sale.pet.breed_profile.photo:
        return sale.pet.breed_profile.photo

    return None


def _get_sale_pet_type_value(sale):
    if sale.pet:
        return sale.pet.pet_type or "dog"

    return sale.preorder_pet_type or "dog"


def _get_sale_photo_paths(sale):
    photo_paths = []

    for item in sale.photos.all():
        if item.photo:
            try:
                photo_paths.append(item.photo.path)
            except Exception:
                pass

    if not photo_paths and sale.sale_photo:
        try:
            photo_paths.append(sale.sale_photo.path)
        except Exception:
            pass

    if not photo_paths and sale.pet and sale.pet.photo:
        try:
            photo_paths.append(sale.pet.photo.path)
        except Exception:
            pass

    if (
        not photo_paths
        and sale.pet
        and sale.pet.breed_profile
        and sale.pet.breed_profile.photo
    ):
        try:
            photo_paths.append(sale.pet.breed_profile.photo.path)
        except Exception:
            pass

    return photo_paths


def _set_optional_sale_tracking(sale, request):
    """
    Reads hidden HTML fields and saves them if the model already has those fields.
    This keeps the view safe even before/after migration changes.
    """
    customer_source = request.POST.get("customer_source", "staff_chat") or "staff_chat"
    commission_mode = request.POST.get("commission_mode", "seller") or "seller"
    lead_owner_id = request.POST.get("lead_owner", "") or None
    seller_id = request.POST.get("seller", "") or None

    if hasattr(sale, "customer_source"):
        sale.customer_source = customer_source

    if hasattr(sale, "commission_mode"):
        sale.commission_mode = commission_mode

    if hasattr(sale, "seller_id") and seller_id:
        sale.seller_id = seller_id

    if hasattr(sale, "lead_owner_id"):
        if lead_owner_id:
            sale.lead_owner_id = lead_owner_id
        else:
            sale.lead_owner = None

    return sale


# =========================================================
# CUSTOMER AUTO CREATE / OLD-NEW CUSTOMER / POINTS
# =========================================================

def _find_customer_from_sale(sale):
    name = (sale.customer_name or "").strip()
    phone = (sale.phone or "").strip()

    customer = None

    if phone:
        customer = Customer.objects.filter(phone=phone).order_by("id").first()

    if not customer and name:
        customer = Customer.objects.filter(name__iexact=name).order_by("id").first()

    return customer


def _get_or_create_customer_from_sale(request, sale):
    """
    Recognize old/new customer immediately from pet sale.

    Priority:
    1. phone match
    2. name match
    3. create new customer

    Returns:
    customer, is_new_customer
    """
    name = (sale.customer_name or "").strip()
    phone = (sale.phone or "").strip()
    address = (sale.address or "").strip()

    if not name:
        name = "Walk-in Customer"

    customer = _find_customer_from_sale(sale)

    if customer:
        old_name = customer.name
        old_phone = customer.phone
        old_address = customer.address
        changed = False

        if name and customer.name != name:
            customer.name = name
            changed = True

        if phone and customer.phone != phone:
            customer.phone = phone
            changed = True

        if address and customer.address != address:
            customer.address = address
            changed = True

        if changed:
            customer.updated_by = request.user
            customer.save()

            CustomerHistory.objects.create(
                customer=customer,
                field_name="customer_info",
                old_value=f"Name: {old_name}, Phone: {old_phone}, Address: {old_address}",
                new_value=f"Name: {customer.name}, Phone: {customer.phone}, Address: {customer.address}",
                changed_by=request.user,
            )

        return customer, False

    customer = Customer.objects.create(
        name=name,
        phone=phone,
        address=address,
        created_by=request.user,
        updated_by=request.user,
    )

    CustomerHistory.objects.create(
        customer=customer,
        field_name="created_from_pet_sale",
        old_value="",
        new_value=f"Created from Pet Sale #{sale.id}",
        changed_by=request.user,
    )

    return customer, True


def sync_sale_customer_only(request, sale):
    """
    Auto create/find customer even when sale is only deposit/preorder.
    This does NOT add points. Points add only when sale is completed.
    """
    customer, is_new_customer = _get_or_create_customer_from_sale(request, sale)

    sale._customer_obj = customer
    sale._customer_is_new = is_new_customer

    CustomerHistory.objects.create(
        customer=customer,
        field_name="pet_sale_seen",
        old_value="",
        new_value=(
            f"{'New' if is_new_customer else 'Old'} customer used in Pet Sale #{sale.id}. "
            f"Status: {sale.get_status_display()}"
        ),
        changed_by=request.user,
    )

    return customer, is_new_customer


def get_sale_customer_badge(sale):
    if hasattr(sale, "_customer_is_new"):
        customer = getattr(sale, "_customer_obj", None)
        return ("New Customer" if sale._customer_is_new else "Old Customer"), customer

    customer = _find_customer_from_sale(sale)

    if customer:
        return "Old Customer", customer

    return "New Customer", None


def sync_completed_pet_sale_to_customer(request, sale):
    """
    When pet sale is completed:
    1. Find or create customer
    2. Add point and total spent once
    3. Create/update customer pet profile
    """
    if sale.status != "completed":
        return None

    customer, is_new_customer = _get_or_create_customer_from_sale(request, sale)

    sale._customer_obj = customer
    sale._customer_is_new = is_new_customer

    existing_customer_pet = CustomerPet.objects.filter(
        pet_sale=sale,
    ).order_by("id").first()

    points_to_add = int(sale.sale_price or Decimal("0.00"))
    amount_to_add = sale.sale_price or Decimal("0.00")

    if existing_customer_pet:
        existing_customer_pet.customer = customer
        existing_customer_pet.pet_name = sale.pet_name_display or existing_customer_pet.pet_name
        existing_customer_pet.pet_type = _get_sale_pet_type_value(sale)
        existing_customer_pet.breed = sale.breed_display or ""
        existing_customer_pet.gender = sale.gender_display or ""
        existing_customer_pet.color = sale.color_display or ""
        existing_customer_pet.source = "bubu_preorder" if sale.sale_kind == "preorder" else "bubu_sale"
        existing_customer_pet.bought_date = timezone.localdate()
        existing_customer_pet.warranty_start_date = sale.warranty_start_date
        existing_customer_pet.warranty_expire_date = sale.warranty_expire_date
        existing_customer_pet.note = sale.note or ""

        photo = _get_sale_first_photo(sale)
        if photo and not existing_customer_pet.photo:
            existing_customer_pet.photo = photo

        existing_customer_pet.save()

        return customer

    old_points = customer.points
    old_total_spent = customer.total_spent

    customer.points = int(customer.points or 0) + points_to_add
    customer.total_spent = (customer.total_spent or Decimal("0.00")) + amount_to_add

    if not customer.pet_type:
        customer.pet_type = sale.pet_type_display or ""

    if not customer.pet_name:
        customer.pet_name = sale.pet_name_display or sale.breed_display or ""

    customer.updated_by = request.user
    customer.save()

    CustomerHistory.objects.create(
        customer=customer,
        field_name="pet_sale_points",
        old_value=f"Points: {old_points}, Total Spent: {old_total_spent}",
        new_value=f"Points: {customer.points}, Total Spent: {customer.total_spent}, Sale #{sale.id}",
        changed_by=request.user,
    )

    CustomerPet.objects.create(
        customer=customer,
        photo=_get_sale_first_photo(sale),
        pet_name=sale.pet_name_display or "",
        pet_type=_get_sale_pet_type_value(sale),
        breed=sale.breed_display or "",
        gender=sale.gender_display or "",
        color=sale.color_display or "",
        age_text=sale.age_display or "",
        source="bubu_preorder" if sale.sale_kind == "preorder" else "bubu_sale",
        bought_date=timezone.localdate(),
        pet_sale=sale,
        warranty_start_date=sale.warranty_start_date,
        warranty_expire_date=sale.warranty_expire_date,
        note=sale.note or "",
        created_by=request.user,
    )

    CustomerHistory.objects.create(
        customer=customer,
        field_name="customer_pet",
        old_value="",
        new_value=f"Recorded pet from Sale #{sale.id}: {sale.pet_type_display} - {sale.breed_display}",
        changed_by=request.user,
    )

    return customer


def complete_pet_sale(request, sale, extra_paid=None, warranty_days=None):
    if extra_paid is not None:
        sale.paid_amount = (sale.paid_amount or Decimal("0.00")) + extra_paid

    if sale.sale_price and sale.paid_amount < sale.sale_price:
        sale.paid_amount = sale.sale_price

    if warranty_days:
        try:
            sale.warranty_days = int(warranty_days)
        except ValueError:
            sale.warranty_days = 3

    sale.status = "completed"
    sale.completed_at = timezone.now()
    sale.set_warranty_dates()
    sale.save()

    sync_completed_pet_sale_to_customer(request, sale)

    return sale


# =========================================================
# TELEGRAM BOT MESSAGE
# =========================================================

def get_pet_sale_main_topic_id(sale):
    if sale.sale_kind == "preorder":
        return getattr(settings, "TELEGRAM_PET_PREORDER_TOPIC_ID", "")

    return getattr(settings, "TELEGRAM_PET_INSTOCK_TOPIC_ID", "")


def get_pet_sale_complete_topic_id():
    return getattr(settings, "TELEGRAM_PET_COMPLETE_TOPIC_ID", "")


def get_sale_seller_name(sale):
    if getattr(sale, "seller", None):
        return _display_user(sale.seller)

    if sale.created_by:
        return _display_user(sale.created_by)

    return "-"


def get_sale_lead_owner_name(sale):
    lead_owner = getattr(sale, "lead_owner", None)
    return _display_user(lead_owner) if lead_owner else "-"


def get_customer_source_display_safe(sale):
    source = getattr(sale, "customer_source", "") or "staff_chat"

    source_map = {
        "walk_in": "Walk-in",
        "staff_chat": "Staff Chat",
        "page_chat": "Page Chat",
        "delivery": "Delivery",
        "referral": "Referral",
    }

    return source_map.get(source, source)


def get_commission_display_safe(sale):
    mode = getattr(sale, "commission_mode", "") or "seller"

    mode_map = {
        "auto": "Auto",
        "seller": "Seller / Staff",
        "lead_owner": "Lead Owner",
        "shared": "Shared",
        "none": "No Commission",
    }

    return mode_map.get(mode, mode)


def get_sale_pet_line(sale):
    pet_type = sale.pet_type_display or "Pet"
    breed = sale.breed_display or "-"
    return f"{pet_type} - {breed}"


def get_sale_seller_block(sale):
    seller_name = get_sale_seller_name(sale)
    lead_owner_name = get_sale_lead_owner_name(sale)
    source_text = get_customer_source_display_safe(sale)
    commission_text = get_commission_display_safe(sale)

    if source_text == "Staff Chat":
        return (
            f"Seller : {seller_name}\n"
            f"Chat Owner : {lead_owner_name}\n"
            f"Commission : {commission_text}"
        )

    if source_text == "Walk-in":
        return (
            f"Seller : {seller_name}\n"
            f"Commission : Shared"
        )

    return (
        f"Seller : {seller_name}\n"
        f"Commission : {commission_text}"
    )


def send_pet_sale_telegram_alert(
    sale,
    complete_only=False,
    first_paid_amount=None,
    final_paid_amount=None,
):
    main_topic_id = get_pet_sale_main_topic_id(sale)
    complete_topic_id = get_pet_sale_complete_topic_id()

    full_price = sale.sale_price or Decimal("0.00")
    paid_amount = sale.paid_amount or Decimal("0.00")
    balance_amount = sale.remaining_amount or Decimal("0.00")

    first_paid = first_paid_amount
    if first_paid is None:
        first_paid = paid_amount

    final_paid = final_paid_amount
    if final_paid is None:
        final_paid = Decimal("0.00")

    created_date = date_text(sale.created_at.date() if sale.created_at else None)
    completed_date = date_text(sale.completed_at.date() if sale.completed_at else timezone.localdate())

    source_text = get_customer_source_display_safe(sale)
    seller_block = get_sale_seller_block(sale)

    customer_badge, customer_obj = get_sale_customer_badge(sale)
    customer_points = getattr(customer_obj, "points", 0) if customer_obj else 0
    customer_total_spent = getattr(customer_obj, "total_spent", Decimal("0.00")) if customer_obj else Decimal("0.00")

    customer_block = (
        f"Customer Type : {customer_badge}\n"
        f"Customer Points : {customer_points}\n"
        f"Customer Total Spent : {money_text(customer_total_spent)}"
    )

    if sale.status == "completed" or complete_only:
        text = (
            "✅ BUBU Pet Sale Completed / Customer Received\n\n"
            f"Sale ID: #{sale.id}\n"
            "Type: completed\n"
            f"Customer : {source_text}\n"
            f"{customer_block}\n"
            f"{seller_block}\n\n"
            "🐶 Pet Info\n"
            f"Pet: {get_sale_pet_line(sale)}\n"
            f"Sex: {sale.gender_display or '-'}\n"
            f"Color: {sale.color_display or '-'}\n\n"
            "💵 Payment\n"
            f"Full Price: {money_text(full_price)}\n"
            f"First payment: {money_text(first_paid)} on {created_date}\n"
            f"Final payment: {money_text(final_paid)} on {completed_date}\n\n"
            "📅 Date Info\n"
            f"Warranty Start: {date_text(sale.warranty_start_date)}"
        )

    elif sale.sale_kind == "preorder":
        text = (
            "📝 BUBU Pet Pre-order Alert\n\n"
            f"Sale ID: #{sale.id}\n"
            f"Status: {sale.get_status_display()}\n"
            f"Customer : {source_text}\n"
            f"{customer_block}\n"
            f"{seller_block}\n\n"
            "🐶 Pet Info\n"
            f"Pet: {sale.pet_type_display or 'Pet'} - {sale.breed_display or '-'}\n"
            f"Sex: {sale.gender_display or '-'}\n"
            f"Color: {sale.color_display or '-'}\n"
            f"📝 Note: {sale.note or '-'}\n\n"
            "💵 Payment\n"
            f"Full Price: {money_text(full_price)}\n"
            f"Paid / Deposit: {money_text(paid_amount)}\n"
            f"Balance: {money_text(balance_amount)}\n\n"
            "📅 Date Info\n"
            f"Pre-Dates: {created_date}\n"
            f"Deadline: {date_text(sale.deadline)}"
        )

    else:
        text = (
            "🛒 BUBU Pet Sale Instock Alert\n\n"
            f"Sale ID: #{sale.id}\n"
            f"Status: {sale.get_status_display()}\n"
            f"Customer : {source_text}\n"
            f"{customer_block}\n"
            f"{seller_block}\n\n"
            "🐶 Pet Info\n"
            f"Pet: {get_sale_pet_line(sale)}\n"
            f"Sex: {sale.gender_display or '-'}\n"
            f"Color: {sale.color_display or '-'}\n\n"
            "💵 Payment\n"
            f"Full Price: {money_text(full_price)}\n"
            f"Paid / Deposit: {money_text(paid_amount)}\n"
            f"Balance: {money_text(balance_amount)}\n\n"
            "📅 Date Info\n"
            f"Warranty Start: {date_text(sale.warranty_start_date)}"
        )

    photo_paths = _get_sale_photo_paths(sale)

    def send_to_topic(topic_id, message_text, send_photos=True):
        if send_photos and photo_paths:
            send_telegram_photos(
                photo_paths[:6],
                caption=message_text[:1000],
                message_thread_id=topic_id if topic_id else None,
            )
            return True

        send_telegram_message(
            message_text,
            message_thread_id=topic_id if topic_id else None,
        )
        return True

    if complete_only:
        send_to_topic(
            complete_topic_id,
            text,
            send_photos=False,
        )
        return True

    send_to_topic(
        main_topic_id,
        text,
        send_photos=True,
    )

    if sale.status == "completed":
        send_to_topic(
            complete_topic_id,
            text,
            send_photos=False,
        )

    return True


# =========================================================
# PET STOCK / BREED
# =========================================================

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
    pets = (
        Pet.objects
        .select_related("breed_profile", "created_by")
        .all()
        .order_by("-created_at")
    )

    q = request.GET.get("q", "").strip()
    pet_type = request.GET.get("pet_type", "").strip()
    status = request.GET.get("status", "").strip()

    if q:
        pets = pets.filter(
            Q(breed__icontains=q)
            | Q(breed_profile__name__icontains=q)
            | Q(name__icontains=q)
            | Q(color__icontains=q)
            | Q(gender__icontains=q)
            | Q(special_type__icontains=q)
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

            if request.POST.get("remove_photo") == "1":
                pet.photo = None

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

            if request.POST.get("remove_photo") == "1":
                if pet.photo:
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
    pet = get_object_or_404(
        Pet.objects.select_related("breed_profile", "created_by"),
        pk=pk,
    )

    return render(request, "pets/pet_detail.html", {
        "pet": pet,
    })


@login_required
def pet_breed_list(request):
    breeds = PetBreed.objects.all().order_by("pet_type", "name")

    q = request.GET.get("q", "").strip()
    pet_type = request.GET.get("pet_type", "").strip()

    if q:
        breeds = breeds.filter(
            Q(name__icontains=q)
            | Q(note__icontains=q)
            | Q(color_options__icontains=q)
            | Q(sex_options__icontains=q)
            | Q(special_type_options__icontains=q)
        )

    if pet_type:
        breeds = breeds.filter(pet_type=pet_type)

    return render(request, "pets/pet_breed_list.html", {
        "breeds": breeds,
        "q": q,
        "pet_type": pet_type,
    })


@login_required
def pet_breed_create(request):
    if request.method == "POST":
        form = PetBreedForm(request.POST, request.FILES)

        if form.is_valid():
            breed = form.save(commit=False)
            breed.created_by = request.user

            if request.POST.get("remove_photo") == "1":
                breed.photo = None

            breed.save()

            messages.success(request, "Breed created successfully.")
            return redirect("pet_breed_list")
    else:
        form = PetBreedForm()

    return render(request, "pets/pet_breed_form.html", {
        "form": form,
        "breed": None,
    })


@login_required
def pet_breed_edit(request, pk):
    breed = get_object_or_404(PetBreed, pk=pk)

    if request.method == "POST":
        form = PetBreedForm(request.POST, request.FILES, instance=breed)

        if form.is_valid():
            breed = form.save(commit=False)

            if request.POST.get("remove_photo") == "1":
                if breed.photo:
                    breed.photo.delete(save=False)
                breed.photo = None

            breed.save()

            messages.success(request, "Breed updated successfully.")
            return redirect("pet_breed_list")
    else:
        form = PetBreedForm(instance=breed)

    return render(request, "pets/pet_breed_form.html", {
        "form": form,
        "breed": breed,
    })


# =========================================================
# PET SALE
# =========================================================

@login_required
def pet_available_for_sale(request):
    pets = (
        Pet.objects
        .select_related("breed_profile")
        .filter(status="in_stock")
        .order_by("pet_type", "breed_profile__name", "breed", "name")
    )

    q = request.GET.get("q", "").strip()
    pet_type = request.GET.get("pet_type", "").strip()

    if q:
        pets = pets.filter(
            Q(breed__icontains=q)
            | Q(breed_profile__name__icontains=q)
            | Q(name__icontains=q)
            | Q(color__icontains=q)
            | Q(gender__icontains=q)
            | Q(special_type__icontains=q)
            | Q(note__icontains=q)
        )

    if pet_type:
        pets = pets.filter(pet_type=pet_type)

    return render(request, "pets/pet_available_for_sale.html", {
        "pets": pets,
        "q": q,
        "pet_type": pet_type,
    })


@login_required
def pet_sale_list(request):
    sales = (
        PetSale.objects
        .select_related("pet", "pet__breed_profile", "created_by", "seller")
        .prefetch_related("photos")
        .order_by("-created_at")
    )

    q = request.GET.get("q", "").strip()
    sale_kind = request.GET.get("sale_kind", "").strip()
    status = request.GET.get("status", "").strip()

    if q:
        sales = sales.filter(
            Q(customer_name__icontains=q)
            | Q(phone__icontains=q)
            | Q(address__icontains=q)
            | Q(preorder_breed__icontains=q)
            | Q(preorder_gender__icontains=q)
            | Q(preorder_color__icontains=q)
            | Q(preorder_special_type__icontains=q)
            | Q(note__icontains=q)
            | Q(pet__breed__icontains=q)
            | Q(pet__breed_profile__name__icontains=q)
            | Q(pet__name__icontains=q)
            | Q(pet__color__icontains=q)
            | Q(pet__gender__icontains=q)
            | Q(pet__special_type__icontains=q)
            | Q(seller__username__icontains=q)
            | Q(seller__first_name__icontains=q)
            | Q(seller__last_name__icontains=q)
        )

    if sale_kind:
        sales = sales.filter(sale_kind=sale_kind)

    if status:
        sales = sales.filter(status=status)

    total_sales = sales.count()
    total_amount = sum((sale.sale_price for sale in sales), Decimal("0.00"))
    total_paid = sum((sale.paid_amount for sale in sales), Decimal("0.00"))
    total_balance = sum((sale.remaining_amount for sale in sales), Decimal("0.00"))

    return render(request, "pets/pet_sale_list.html", {
        "sales": sales,
        "q": q,
        "sale_kind": sale_kind,
        "status": status,
        "total_sales": total_sales,
        "total_amount": total_amount,
        "total_paid": total_paid,
        "total_balance": total_balance,
    })


@login_required
def pet_sale_create(request):
    selected_pet = None
    pet_id = request.GET.get("pet")

    if pet_id:
        selected_pet = (
            Pet.objects
            .select_related("breed_profile")
            .filter(pk=pet_id, status="in_stock")
            .first()
        )

    if request.method == "POST":
        form = PetSaleForm(request.POST, request.FILES)

        if form.is_valid():
            sale = form.save(commit=False)
            sale.created_by = request.user

            if not getattr(sale, "seller", None):
                sale.seller = request.user

            _set_optional_sale_tracking(sale, request)

            if sale.sale_kind == "preorder":
                sale.pet = None

            sale.save()
            sync_sale_customer_only(request, sale)
            _save_pet_sale_photos(request, sale)

            submit_action = request.POST.get("submit_action", "save")

            if submit_action in ["save_complete", "save_complete_print"]:
                first_paid_before_complete = sale.paid_amount or Decimal("0.00")
                final_paid = (sale.sale_price or Decimal("0.00")) - first_paid_before_complete

                if final_paid < 0:
                    final_paid = Decimal("0.00")

                complete_pet_sale(request, sale)

                send_pet_sale_telegram_alert(
                    sale,
                    complete_only=True,
                    first_paid_amount=first_paid_before_complete,
                    final_paid_amount=final_paid,
                )

                messages.success(request, "Pet sale saved and completed. Customer profile updated.")
            else:
                send_pet_sale_telegram_alert(sale)
                messages.success(request, "Pet sale saved successfully.")

            if submit_action == "save_complete_print":
                return redirect("pet_sale_receipt_print", sale.id)

            return redirect("pet_sale_detail", sale.id)
    else:
        initial = {
            "sale_kind": "in_stock",
            "seller": request.user,
            "warranty_days": 3,
            "paid_amount": Decimal("0.00"),
            "customer_source": "staff_chat",
            "lead_owner": request.user,
            "commission_mode": "seller",
        }

        if selected_pet:
            initial.update({
                "pet": selected_pet,
                "sale_price": selected_pet.sale_price,
                "preorder_pet_type": selected_pet.pet_type,
                "preorder_breed": selected_pet.breed_name,
                "preorder_gender": selected_pet.gender,
                "preorder_color": selected_pet.color,
                "preorder_special_type": selected_pet.special_type,
            })

        form = PetSaleForm(initial=initial)

    pets = (
        Pet.objects
        .select_related("breed_profile")
        .filter(status="in_stock")
        .order_by("pet_type", "breed_profile__name", "breed", "name")
    )

    return render(request, "pets/pet_sale_form.html", {
        "form": form,
        "pets": pets,
        "sellers": _get_active_sellers(),
        "selected_pet": selected_pet,
        "sale": None,
    })


@login_required
def pet_sale_edit(request, pk):
    sale = get_object_or_404(
        PetSale.objects
        .select_related("pet", "pet__breed_profile", "created_by", "seller")
        .prefetch_related("photos"),
        pk=pk,
    )

    if request.method == "POST":
        form = PetSaleForm(request.POST, request.FILES, instance=sale)

        if form.is_valid():
            sale = form.save(commit=False)

            if not getattr(sale, "seller", None):
                sale.seller = request.user

            _set_optional_sale_tracking(sale, request)

            if sale.sale_kind == "preorder":
                sale.pet = None

            sale.save()
            sync_sale_customer_only(request, sale)
            _save_pet_sale_photos(request, sale)

            submit_action = request.POST.get("submit_action", "save")

            if submit_action in ["save_complete", "save_complete_print"]:
                first_paid_before_complete = sale.paid_amount or Decimal("0.00")
                final_paid = (sale.sale_price or Decimal("0.00")) - first_paid_before_complete

                if final_paid < 0:
                    final_paid = Decimal("0.00")

                complete_pet_sale(request, sale)

                send_pet_sale_telegram_alert(
                    sale,
                    complete_only=True,
                    first_paid_amount=first_paid_before_complete,
                    final_paid_amount=final_paid,
                )

                messages.success(request, "Pet sale updated and completed. Customer profile updated.")
            else:
                send_pet_sale_telegram_alert(sale)
                messages.success(request, "Pet sale updated successfully.")

            if submit_action == "save_complete_print":
                return redirect("pet_sale_receipt_print", sale.id)

            return redirect("pet_sale_detail", sale.id)
    else:
        form = PetSaleForm(instance=sale)

    pets = (
        Pet.objects
        .select_related("breed_profile")
        .filter(Q(status="in_stock") | Q(pk=sale.pet_id))
        .order_by("pet_type", "breed_profile__name", "breed", "name")
    )

    return render(request, "pets/pet_sale_form.html", {
        "form": form,
        "pets": pets,
        "sellers": _get_active_sellers(),
        "selected_pet": sale.pet,
        "sale": sale,
    })


@login_required
def pet_sale_detail(request, pk):
    sale = get_object_or_404(
        PetSale.objects
        .select_related("pet", "pet__breed_profile", "created_by", "seller")
        .prefetch_related("photos"),
        pk=pk,
    )

    return render(request, "pets/pet_sale_detail.html", {
        "sale": sale,
        "copy_text": sale.build_copy_text(),
    })


@login_required
def pet_sale_mark_arrived(request, pk):
    sale = get_object_or_404(PetSale, pk=pk)

    if request.method == "POST":
        sale.status = "arrived"
        sale.save()
        messages.success(request, "Marked as arrived.")

    return redirect("pet_sale_detail", sale.id)


@login_required
def pet_sale_complete(request, pk):
    sale = get_object_or_404(
        PetSale.objects
        .select_related("pet", "pet__breed_profile", "created_by", "seller")
        .prefetch_related("photos"),
        pk=pk,
    )

    if request.method == "POST":
        extra_paid = _to_decimal(request.POST.get("extra_paid"), "0.00")
        warranty_days = request.POST.get("warranty_days") or sale.warranty_days or 3
        first_paid_before_complete = sale.paid_amount or Decimal("0.00")

        complete_pet_sale(
            request=request,
            sale=sale,
            extra_paid=extra_paid,
            warranty_days=warranty_days,
        )

        send_pet_sale_telegram_alert(
            sale,
            complete_only=True,
            first_paid_amount=first_paid_before_complete,
            final_paid_amount=extra_paid,
        )

        messages.success(request, "Pet sale completed. Customer profile updated.")

    return redirect("pet_sale_detail", sale.id)


@login_required
def pet_sale_cancel(request, pk):
    sale = get_object_or_404(PetSale, pk=pk)

    if request.method == "POST":
        sale.cancel_reason = request.POST.get("cancel_reason", "").strip()
        sale.status = "cancelled"
        sale.save()
        messages.success(request, "Pet sale cancelled.")

    return redirect("pet_sale_detail", sale.id)


@login_required
def pet_sale_refund(request, pk):
    sale = get_object_or_404(PetSale, pk=pk)

    if request.method == "POST":
        sale.refund_reason = request.POST.get("refund_reason", "").strip()
        sale.status = "refunded"
        sale.save()
        messages.success(request, "Pet sale refunded.")

    return redirect("pet_sale_detail", sale.id)


@login_required
def pet_warranty_print(request, pk):
    sale = get_object_or_404(
        PetSale.objects
        .select_related("pet", "pet__breed_profile", "seller", "created_by")
        .prefetch_related("photos"),
        pk=pk,
    )

    return render(request, "pets/pet_warranty_print.html", {
        "sale": sale,
    })


@login_required
def pet_sale_receipt_print(request, pk):
    sale = get_object_or_404(
        PetSale.objects
        .select_related("pet", "pet__breed_profile", "seller", "created_by")
        .prefetch_related("photos"),
        pk=pk,
    )

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

            messages.success(request, "Warranty claim recorded.")
            return redirect("pet_sale_detail", sale.id)
    else:
        form = PetWarrantyClaimForm()

    return render(request, "pets/pet_warranty_claim_form.html", {
        "form": form,
        "sale": sale,
    })
