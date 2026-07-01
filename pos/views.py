import json
import requests
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q, Sum, F, Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt

from customers.models import Customer
from delivery.models import Delivery, DeliveryItem, DeliveryCompany
from inventory.models import (
    Item,
    ItemType,
    ItemVariant,
    StockMovement,
    Branch,
    BranchStock,
)
from .models import (
    Sale,
    SaleItem,
    SalePayment,
    POSSetting,
    CashCount,
    BranchCashFloat,
    CombinedPaymentSession,
    ABAPaymentSession,
)

from .services.aba_qr import create_real_aba_payment, check_real_aba_payment

from pets.models import PetSale



# ==================================================
# TELEGRAM + PET SALE HELPERS
# ==================================================

def _choice_value(model_class, field_name, candidates, default_value):
    """
    Pick a valid value from model field choices.
    This prevents pet sale status bugs when one project uses completed,
    another uses sold / complete / done.
    """
    try:
        field = model_class._meta.get_field(field_name)
        choices = [str(value) for value, _label in (field.choices or [])]

        if not choices:
            return default_value

        for value in candidates:
            if value in choices:
                return value

        if default_value in choices:
            return default_value

        return choices[0]
    except Exception:
        return default_value


def _safe_attr(obj, attr, default=""):
    try:
        value = getattr(obj, attr, default)
        return value if value not in [None, ""] else default
    except Exception:
        return default


def _send_pet_sale_completed_telegram(pet_sale, sale, branch, cashier):
    """
    Set these in settings.py / .env:
    TELEGRAM_BOT_TOKEN = "xxxxx"
    TELEGRAM_PET_SALE_CHAT_ID = "xxxxx"
    """
    bot_token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    chat_id = getattr(settings, "TELEGRAM_PET_SALE_CHAT_ID", "")

    if not bot_token or not chat_id:
        return False

    pet = getattr(pet_sale, "pet", None)

    breed = (
        _safe_attr(getattr(pet, "breed_profile", None), "name")
        or _safe_attr(pet, "breed")
        or _safe_attr(pet_sale, "breed")
        or "Pet"
    )

    pet_type = (
        _safe_attr(pet, "pet_type")
        or _safe_attr(pet_sale, "pet_type")
        or ""
    )

    customer_name = ""
    customer_phone = ""

    if getattr(sale, "customer", None):
        customer_name = sale.customer.name or ""
        customer_phone = sale.customer.phone or ""

    cashier_name = getattr(cashier, "get_full_name", lambda: "")() or getattr(cashier, "username", "")

    text = (
        "🐶 Pet Sale Completed\n"
        f"Branch: {branch.name if branch else '-'}\n"
        f"POS Sale: #{sale.id}\n"
        f"Pet Sale: #{pet_sale.id}\n"
        f"Pet: {pet_type} {breed}\n"
        f"Total: ${sale.total_amount:.2f}\n"
        f"Paid: ${sale.paid_amount:.2f}\n"
        f"Customer: {customer_name or '-'} {customer_phone or ''}\n"
        f"Cashier: {cashier_name or '-'}"
    )

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data={
                "chat_id": chat_id,
                "text": text,
            },
            timeout=5,
        )
        return response.ok
    except Exception:
        return False


# ==================================================
# BASIC HELPERS
# ==================================================

def money(value, default="0"):
    try:
        return Decimal(str(value or default))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def to_decimal(value, default="0"):
    try:
        if value in [None, ""]:
            return Decimal(default)
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def get_khr_rate():
    setting = POSSetting.objects.first()
    if setting:
        return setting.exchange_rate
    return Decimal("4100")


def is_service_item(item):
    if not item.item_type:
        return False

    name = item.item_type.name.lower().strip()
    return name in ["grooming", "service", "services"]


def get_user_branch(user):
    profile = getattr(user, "staff_profile", None)

    if profile and profile.branch_id:
        return profile.branch

    return None


def get_pos_branch(request):
    """
    POS branch rule:
    - normal staff/cashier: locked to user.staff_profile.branch
    - superuser: can use session branch if set
    - fallback: first active branch
    """
    if request.user.is_superuser:
        branch_id = request.session.get("pos_branch_id")

        if branch_id:
            branch = Branch.objects.filter(
                id=branch_id,
                is_active=True,
            ).first()

            if branch:
                return branch

    user_branch = get_user_branch(request.user)

    if user_branch:
        return user_branch

    return Branch.objects.filter(is_active=True).order_by("id").first()


def _cart_key(item_id, variant_id=None):
    if variant_id:
        return f"{item_id}:{variant_id}"
    return f"{item_id}:0"


def _get_cart(request):
    return request.session.get("cart", {})


def _save_cart(request, cart):
    request.session["cart"] = cart
    request.session.modified = True


def _get_variant_price(item, variant=None):
    if variant and variant.sale_price and variant.sale_price > 0:
        return variant.sale_price
    return item.sale_price


def _get_branch_variant_stock(branch, variant):
    if not branch or not variant:
        return 0

    stock = BranchStock.objects.filter(
        branch=branch,
        variant=variant,
    ).first()

    if not stock:
        return 0

    return int(stock.quantity or 0)


def _get_item_branch_stock(item, branch):
    if is_service_item(item):
        return 999999

    if not branch:
        return 0

    return (
        BranchStock.objects
        .filter(
            branch=branch,
            variant__item=item,
            variant__is_active=True,
        )
        .aggregate(total=Sum("quantity"))["total"]
        or 0
    )


def _build_cart_items(cart, branch=None):
    cart_items = []
    subtotal = Decimal("0.00")

    for key, row in cart.items():
        try:
            item_id = int(row.get("item_id"))
            variant_id = row.get("variant_id")
            qty = int(row.get("qty", 0))
        except (TypeError, ValueError):
            continue

        if qty <= 0:
            continue

        try:
            item = Item.objects.select_related("item_type").get(
                id=item_id,
                is_active=True,
            )
        except Item.DoesNotExist:
            continue

        variant = None

        if variant_id:
            try:
                variant = ItemVariant.objects.select_related("item").get(
                    id=variant_id,
                    item=item,
                    is_active=True,
                )
            except ItemVariant.DoesNotExist:
                variant = None

        price = _get_variant_price(item, variant)
        line_total = price * qty
        subtotal += line_total

        image_url = ""

        if variant and variant.image:
            image_url = variant.image.url
        elif item.image:
            image_url = item.image.url

        if variant:
            branch_stock = _get_branch_variant_stock(branch, variant)
        else:
            branch_stock = _get_item_branch_stock(item, branch)

        item_type_name = ""
        if item.item_type:
            item_type_name = item.item_type.name.strip()

        cart_items.append({
            "cart_key": key,
            "item": item,
            "variant": variant,
            "item_id": item.id,
            "variant_id": variant.id if variant else None,
            "name": item.name,
            "variant_label": variant.display_name() if variant else "",
            "image_url": image_url,
            "quantity": qty,
            "price": price,
            "total": line_total,
            "branch_stock": branch_stock,
            "is_service": is_service_item(item),
            "item_type_name": item_type_name,
        })

    return cart_items, subtotal


def _add_to_cart(request, item, variant=None):
    cart = _get_cart(request)
    key = _cart_key(item.id, variant.id if variant else None)

    if key not in cart:
        cart[key] = {
            "item_id": item.id,
            "variant_id": variant.id if variant else None,
            "qty": 0,
        }

    cart[key]["qty"] = int(cart[key].get("qty", 0)) + 1
    _save_cart(request, cart)


def _deduct_selected_variant_from_branch(item, variant, qty, user, sale, branch):
    """
    Do NOT manually edit BranchStock here.
    StockMovement.save() updates BranchStock.
    This prevents double deduction.
    """
    if is_service_item(item):
        return

    if not branch:
        raise ValueError("No branch selected for POS sale.")

    if not variant:
        raise ValueError("No variant selected for stock item.")

    StockMovement.objects.create(
        branch=branch,
        item=item,
        variant=variant,
        movement_type="sale",
        quantity=qty,
        cost_price=variant.cost_price or item.cost_price,
        note=f"Sale #{sale.id} - {branch.name} - {variant.display_name()}",
        created_by=user,
    )


def _find_best_variant_for_branch(item, branch):
    stocks = (
        BranchStock.objects
        .filter(
            branch=branch,
            variant__item=item,
            variant__is_active=True,
        )
        .select_related("variant")
        .order_by("-quantity", "variant_id")
    )

    first_stock = stocks.first()

    if first_stock:
        return first_stock.variant

    return item.variants.filter(is_active=True).order_by("id").first()


# ==================================================
# AJAX CART HELPERS
# ==================================================

def _is_ajax(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _build_pos_cart_context(request):
    current_branch = get_pos_branch(request)
    cart = _get_cart(request)
    cart_items, subtotal = _build_cart_items(cart, current_branch)

    product_total = Decimal("0.00")
    grooming_total = Decimal("0.00")
    service_total = Decimal("0.00")
    pet_total = Decimal("0.00")

    for cart_item in cart_items:
        type_name = (cart_item.get("item_type_name") or "").lower()
        line_total = cart_item["total"]

        if "groom" in type_name:
            grooming_total += line_total
        elif "service" in type_name:
            service_total += line_total
        elif (
            "pet" in type_name
            or "dog" in type_name
            or "cat" in type_name
            or "puppy" in type_name
        ):
            pet_total += line_total
        else:
            product_total += line_total

    selected_pet_sale = None
    selected_pet_full_price = Decimal("0.00")
    selected_pet_paid = Decimal("0.00")
    selected_pet_remaining = Decimal("0.00")

    selected_pet_sale_id = request.session.get("selected_pet_sale_id")

    if selected_pet_sale_id:
        selected_pet_sale = (
            PetSale.objects
            .select_related("pet", "pet__breed_profile")
            .filter(id=selected_pet_sale_id)
            .first()
        )

        if selected_pet_sale:
            selected_pet_full_price = selected_pet_sale.sale_price or Decimal("0.00")
            selected_pet_paid = selected_pet_sale.paid_amount or Decimal("0.00")
            selected_pet_remaining = selected_pet_sale.remaining_amount or Decimal("0.00")

            if selected_pet_remaining <= 0:
                selected_pet_remaining = selected_pet_full_price - selected_pet_paid

            if selected_pet_remaining < 0:
                selected_pet_remaining = Decimal("0.00")

    final_total = subtotal + selected_pet_remaining

    return {
        "cart_items": cart_items,
        "subtotal": subtotal,
        "discount": Decimal("0.00"),
        "tax": Decimal("0.00"),
        "total": final_total,
        "product_total": product_total,
        "grooming_total": grooming_total,
        "service_total": service_total,
        "pet_total": pet_total,
        "selected_pet_sale": selected_pet_sale,
        "selected_pet_full_price": selected_pet_full_price,
        "selected_pet_paid": selected_pet_paid,
        "selected_pet_remaining": selected_pet_remaining,
        "current_branch": current_branch,
    }


def _cart_ajax_response(request, success=True, message=""):
    ctx = _build_pos_cart_context(request)
    cart_html = render_to_string(
        "pos/partials/cart_panel.html",
        ctx,
        request=request,
    )

    return JsonResponse({
        "success": success,
        "message": message,
        "cart_html": cart_html,
        "cart_count": sum(int(item["quantity"]) for item in ctx["cart_items"]),
        "subtotal": f"{ctx['subtotal']:.2f}",
        "total": f"{ctx['total']:.2f}",
        "product_total": f"{ctx['product_total']:.2f}",
        "grooming_total": f"{ctx['grooming_total']:.2f}",
        "service_total": f"{ctx['service_total']:.2f}",
        "pet_total": f"{ctx['pet_total']:.2f}",
        "selected_pet_remaining": f"{ctx['selected_pet_remaining']:.2f}",
    })


# ==================================================
# POS MAIN / ADMIN BRANCH SWITCH
# ==================================================

@login_required
def pos_switch_branch(request):
    if not request.user.is_superuser:
        messages.error(
            request,
            "You cannot change shop. Your POS is locked to your assigned branch.",
        )
        return redirect("pos")

    if request.method != "POST":
        return redirect("pos")

    branch_id = request.POST.get("branch_id")

    branch = Branch.objects.filter(
        id=branch_id,
        is_active=True,
    ).first()

    if not branch:
        messages.error(request, "Invalid shop selected.")
        return redirect("pos")

    request.session["pos_branch_id"] = branch.id
    request.session.modified = True

    _save_cart(request, {})

    messages.success(request, f"POS switched to {branch.name}. Cart cleared for safety.")
    return redirect("pos")


@login_required
def pos(request):
    current_branch = get_pos_branch(request)

    if not current_branch:
        messages.error(request, "No branch assigned. Please ask admin to set your shop.")
        return redirect("dashboard")

    branches = Branch.objects.filter(is_active=True).order_by("name")
    delivery_companies = DeliveryCompany.objects.filter(
        is_active=True
    ).order_by("delivery_type", "name")

    raw_q = request.GET.get("q", "").strip()
    q = raw_q
    type_id = request.GET.get("type", "").strip()

    if q.upper().startswith("SKU:"):
        q = q.split(":", 1)[1].strip()

    active_variants_qs = ItemVariant.objects.filter(is_active=True).order_by(
        "sale_price",
        "size",
        "color",
        "label",
        "id",
    )

    items = (
        Item.objects
        .filter(is_active=True)
        .select_related("item_type")
        .prefetch_related(Prefetch("variants", queryset=active_variants_qs))
        .order_by("name")
    )

    item_types = ItemType.objects.filter(is_active=True).order_by("name")
    customers = Customer.objects.all().order_by("name", "phone")

    # ==================================================
    # SCAN / SEARCH ADD TO CART
    # ==================================================
    if q:
        variant = (
            ItemVariant.objects
            .select_related("item", "item__item_type")
            .filter(
                item__is_active=True,
                is_active=True,
                sku__iexact=q,
            )
            .first()
        )

        if variant:
            _add_to_cart(request, variant.item, variant)
            messages.success(
                request,
                f"Added {variant.item.name} - {variant.display_name()}",
            )
            return redirect("pos")

        exact_item = (
            Item.objects
            .filter(is_active=True)
            .filter(Q(name__iexact=q) | Q(variants__sku__iexact=q))
            .distinct()
            .first()
        )

        if exact_item:
            active_variants = exact_item.variants.filter(is_active=True)

            if active_variants.count() == 1:
                variant = active_variants.first()
                _add_to_cart(request, exact_item, variant)
                messages.success(request, f"Added {exact_item.name}")
                return redirect("pos")

            if active_variants.count() == 0 or is_service_item(exact_item):
                _add_to_cart(request, exact_item, None)
                messages.success(request, f"Added {exact_item.name}")
                return redirect("pos")

    # ==================================================
    # FILTER PRODUCT LIST
    # ==================================================
    if q:
        items = items.filter(
            Q(name__icontains=q)
            | Q(brand__icontains=q)
            | Q(item_type__name__icontains=q)
            | Q(variants__sku__icontains=q)
            | Q(variants__color__icontains=q)
            | Q(variants__size__icontains=q)
            | Q(variants__label__icontains=q)
        ).distinct()

    if type_id:
        items = items.filter(item_type_id=type_id)

    # ==================================================
    # STOCK MAP
    # ==================================================
    item_stock_map = {}
    variant_stock_map = {}

    branch_stocks = (
        BranchStock.objects
        .filter(
            branch=current_branch,
            variant__item__in=items,
            variant__is_active=True,
        )
        .select_related("variant", "variant__item")
    )

    for stock in branch_stocks:
        item_id = stock.variant.item_id
        variant_id = stock.variant_id
        qty = int(stock.quantity or 0)

        item_stock_map[item_id] = item_stock_map.get(item_id, 0) + qty
        variant_stock_map[variant_id] = qty

    # ==================================================
    # COMING SOON MAP
    # ==================================================
    try:
        from purchases.models import PurchaseItem

        purchase_data = PurchaseItem.objects.values("variant_id").annotate(
            ordered=Sum("ordered_qty"),
            received=Sum("received_qty"),
        )

        coming_map = {}

        for row in purchase_data:
            variant_id = row["variant_id"]

            if not variant_id:
                continue

            coming_qty = (row["ordered"] or 0) - (row["received"] or 0)

            if coming_qty > 0:
                coming_map[variant_id] = coming_qty

    except Exception:
        coming_map = {}

    for item in items:
        item.branch_stock_total = item_stock_map.get(item.id, 0)
        item_coming_soon_qty = 0

        for variant in item.variants.all():
            variant.branch_stock_qty = variant_stock_map.get(variant.id, 0)
            variant.coming_soon_qty = coming_map.get(variant.id, 0)
            variant.is_coming_soon = variant.coming_soon_qty > 0
            item_coming_soon_qty += variant.coming_soon_qty

        item.coming_soon_qty = item_coming_soon_qty
        item.is_coming_soon = item_coming_soon_qty > 0

    # ==================================================
    # CART TOTAL
    # ==================================================
    cart = _get_cart(request)
    cart_items, subtotal = _build_cart_items(cart, current_branch)

    product_total = Decimal("0.00")
    grooming_total = Decimal("0.00")
    service_total = Decimal("0.00")
    pet_total = Decimal("0.00")

    for cart_item in cart_items:
        type_name = (cart_item.get("item_type_name") or "").lower()
        line_total = cart_item["total"]

        if "groom" in type_name:
            grooming_total += line_total
        elif "service" in type_name:
            service_total += line_total
        elif (
            "pet" in type_name
            or "dog" in type_name
            or "cat" in type_name
            or "puppy" in type_name
        ):
            pet_total += line_total
        else:
            product_total += line_total

    # ==================================================
    # SELECTED PET SALE FROM PET MODULE
    # ==================================================
    selected_pet_sale = None
    selected_pet_full_price = Decimal("0.00")
    selected_pet_paid = Decimal("0.00")
    selected_pet_remaining = Decimal("0.00")

    selected_pet_sale_id = request.session.get("selected_pet_sale_id")

    if selected_pet_sale_id:
        selected_pet_sale = (
            PetSale.objects
            .select_related("pet", "pet__breed_profile")
            .filter(id=selected_pet_sale_id)
            .first()
        )

        if selected_pet_sale:
            selected_pet_full_price = selected_pet_sale.sale_price or Decimal("0.00")
            selected_pet_paid = selected_pet_sale.paid_amount or Decimal("0.00")

            selected_pet_remaining = selected_pet_sale.remaining_amount or Decimal("0.00")

            if selected_pet_remaining <= 0:
                selected_pet_remaining = selected_pet_full_price - selected_pet_paid

            if selected_pet_remaining < 0:
                selected_pet_remaining = Decimal("0.00")

    final_total = subtotal + selected_pet_remaining

    return render(request, "pos/pos.html", {
        "items": items,
        "item_types": item_types,
        "cart_items": cart_items,

        "subtotal": subtotal,
        "discount": Decimal("0.00"),
        "tax": Decimal("0.00"),
        "total": final_total,

        "product_total": product_total,
        "grooming_total": grooming_total,
        "service_total": service_total,
        "pet_total": pet_total,

        "selected_pet_sale": selected_pet_sale,
        "selected_pet_full_price": selected_pet_full_price,
        "selected_pet_paid": selected_pet_paid,
        "selected_pet_remaining": selected_pet_remaining,

        "khr_rate": get_khr_rate(),
        "selected_type": type_id,
        "q": raw_q,
        "customers": customers,
        "delivery_companies": delivery_companies,
        "current_branch": current_branch,
        "branches": branches,
    })

# ==================================================
# CART ACTIONS
# ==================================================

@login_required
def pos_add_cart(request, item_id):
    current_branch = get_pos_branch(request)

    if not current_branch:
        if _is_ajax(request):
            return JsonResponse({
                "success": False,
                "message": "No branch assigned. Please ask admin to set your shop.",
            }, status=400)

        messages.error(
            request,
            "No branch assigned. Please ask admin to set your shop.",
        )
        return redirect("pos")

    item = get_object_or_404(
        Item.objects.select_related("item_type").prefetch_related("variants"),
        id=item_id,
        is_active=True,
    )

    if is_service_item(item):
        _add_to_cart(request, item, None)

        if _is_ajax(request):
            return _cart_ajax_response(request, message=f"Added {item.name}")

        return redirect("pos")

    active_variants = item.variants.filter(is_active=True)

    if active_variants.count() > 1:
        if _is_ajax(request):
            return JsonResponse({
                "success": False,
                "message": "Please select variant first.",
            }, status=400)

        messages.error(request, "Please select variant first.")
        return redirect("pos")

    variant = active_variants.first()

    if not variant:
        if _is_ajax(request):
            return JsonResponse({
                "success": False,
                "message": "This product has no active variant.",
            }, status=400)

        messages.error(request, "This product has no active variant.")
        return redirect("pos")

    _add_to_cart(request, item, variant)

    if _is_ajax(request):
        return _cart_ajax_response(request, message=f"Added {item.name}")

    return redirect("pos")


@login_required
def pos_add_variant_cart(request, item_id, variant_id):
    current_branch = get_pos_branch(request)

    if not current_branch:
        if _is_ajax(request):
            return JsonResponse({
                "success": False,
                "message": "No branch assigned. Please ask admin to set your shop.",
            }, status=400)

        messages.error(
            request,
            "No branch assigned. Please ask admin to set your shop.",
        )
        return redirect("pos")

    item = get_object_or_404(
        Item.objects.select_related("item_type"),
        id=item_id,
        is_active=True,
    )

    variant = get_object_or_404(
        ItemVariant,
        id=variant_id,
        item=item,
        is_active=True,
    )

    _add_to_cart(request, item, variant)

    if _is_ajax(request):
        return _cart_ajax_response(request, message=f"Added {item.name}")

    return redirect("pos")


@login_required
def pos_plus_cart(request, cart_key):
    cart = _get_cart(request)

    if cart_key in cart:
        current_qty = int(cart[cart_key].get("qty", 0))
        cart[cart_key]["qty"] = current_qty + 1

    _save_cart(request, cart)

    if _is_ajax(request):
        return _cart_ajax_response(request)

    return redirect("pos")


@login_required
def pos_minus_cart(request, cart_key):
    cart = _get_cart(request)

    if cart_key in cart:
        cart[cart_key]["qty"] = int(cart[cart_key].get("qty", 0)) - 1

        if cart[cart_key]["qty"] <= 0:
            del cart[cart_key]

    _save_cart(request, cart)

    if _is_ajax(request):
        return _cart_ajax_response(request)

    return redirect("pos")


@login_required
def pos_remove_cart(request, cart_key):
    cart = _get_cart(request)
    cart.pop(cart_key, None)
    _save_cart(request, cart)

    if _is_ajax(request):
        return _cart_ajax_response(request)

    return redirect("pos")


@login_required
def pos_clear_cart(request):
    _save_cart(request, {})

    if _is_ajax(request):
        return _cart_ajax_response(request, message="Cart cleared.")

    messages.success(request, "Cart cleared.")
    return redirect("pos")


# ==================================================
# CHECKOUT
# ==================================================

@login_required
@transaction.atomic
def pos_checkout(request):
    if request.method != "POST":
        return redirect("pos")

    branch = get_pos_branch(request)

    if not branch:
        messages.error(request, "Please select a shop/branch first.")
        return redirect("pos")

    # ==================================================
    # CART + ATTACHED PET SALE
    # ==================================================
    cart = _get_cart(request)
    cart_items, cart_subtotal = _build_cart_items(cart, branch)

    selected_pet_sale = None
    selected_pet_remaining = Decimal("0.00")

    selected_pet_sale_id = (
        request.POST.get("selected_pet_sale_id")
        or request.session.get("selected_pet_sale_id")
    )

    if selected_pet_sale_id:
        selected_pet_sale = (
            PetSale.objects
            .select_for_update()
            .select_related("pet")
            .filter(id=selected_pet_sale_id)
            .first()
        )

        if selected_pet_sale:
            selected_pet_remaining = selected_pet_sale.remaining_amount or Decimal("0.00")

            if selected_pet_remaining <= 0:
                selected_pet_remaining = (
                    selected_pet_sale.sale_price or Decimal("0.00")
                ) - (
                    selected_pet_sale.paid_amount or Decimal("0.00")
                )

            if selected_pet_remaining < 0:
                selected_pet_remaining = Decimal("0.00")

    if not cart_items and not selected_pet_sale:
        messages.error(request, "Cart is empty.")
        return redirect("pos")

    subtotal = cart_subtotal + selected_pet_remaining

    checkout_action = request.POST.get("checkout_action", "complete")
    sale_type = request.POST.get("sale_type", "walk_in")

    discount_type = request.POST.get("discount_type", "percent")
    discount_value = to_decimal(request.POST.get("discount_value"), "0")
    tax_type = request.POST.get("tax_type", "percent")
    tax_value = to_decimal(request.POST.get("tax_value"), "0")

    discount_amount = Decimal("0.00")
    tax_amount = Decimal("0.00")

    if discount_value > 0:
        if discount_type == "percent":
            discount_amount = subtotal * discount_value / Decimal("100")
        else:
            discount_amount = discount_value

    if discount_amount > subtotal:
        discount_amount = subtotal

    after_discount = subtotal - discount_amount

    if tax_value > 0:
        if tax_type == "percent":
            tax_amount = after_discount * tax_value / Decimal("100")
        else:
            tax_amount = tax_value

    final_total = after_discount + tax_amount

    cash_usd = to_decimal(request.POST.get("cash_usd"))
    cash_khr = to_decimal(request.POST.get("cash_khr"))
    aba_usd = to_decimal(request.POST.get("aba_usd"))
    aba_khr = to_decimal(request.POST.get("aba_khr"))

    delivery_fee = to_decimal(request.POST.get("delivery_expense"), "0")

    exchange_rate = get_khr_rate()
    if exchange_rate <= 0:
        exchange_rate = Decimal("4100")

    paid_raw = (
        cash_usd
        + aba_usd
        + (cash_khr / exchange_rate)
        + (aba_khr / exchange_rate)
    )

    paid_amount = min(paid_raw, final_total)

    change_amount = Decimal("0.00")
    if paid_raw > final_total:
        change_amount = paid_raw - final_total

    balance_amount = final_total - paid_amount

    # ==================================================
    # CUSTOMER RECORD
    # ==================================================
    customer = None

    customer_phone = request.POST.get("customer_phone", "").strip()
    customer_name = request.POST.get("customer_name", "").strip()
    customer_search = request.POST.get("customer_search", "").strip()

    delivery_receiver_name_for_customer = request.POST.get(
        "delivery_receiver_name",
        "",
    ).strip()

    delivery_phone_for_customer = request.POST.get(
        "delivery_phone",
        "",
    ).strip()

    if not customer_name and delivery_receiver_name_for_customer:
        customer_name = delivery_receiver_name_for_customer

    if not customer_phone and delivery_phone_for_customer:
        customer_phone = delivery_phone_for_customer

    if not customer_name and customer_search:
        customer_name = customer_search

    if not customer_phone and customer_search:
        customer_phone = customer_search

    if customer_phone:
        customer = Customer.objects.filter(phone=customer_phone).first()

        if not customer:
            customer = Customer.objects.create(
                name=customer_name or customer_phone,
                phone=customer_phone,
                created_by=request.user,
                updated_by=request.user,
            )
        else:
            update_fields = []

            if customer_name and customer.name != customer_name:
                customer.name = customer_name
                update_fields.append("name")

            customer.updated_by = request.user
            update_fields.append("updated_by")

            customer.save(update_fields=update_fields + ["updated_at"])

    elif customer_name:
        customer = Customer.objects.create(
            name=customer_name,
            phone="",
            created_by=request.user,
            updated_by=request.user,
        )

    # ==================================================
    # CREATE POS SALE
    # ==================================================
    sale = Sale.objects.create(
        branch=branch,
        customer=customer,
        sale_type=sale_type,
        total_amount=final_total,
        paid_amount=paid_amount,
        change_amount=change_amount,
        discount_type=discount_type,
        discount_value=discount_value,
        discount_amount=discount_amount,
        tax_type=tax_type,
        tax_value=tax_value,
        tax_amount=tax_amount,
    )

    # Keep a permanent link between this POS receipt and the attached pet sale.
    # This preserves:
    # - normal POS goods total
    # - pet full price
    # - deposit paid before POS
    # - pet balance included in this POS payment
    #
    # CombinedPaymentSession already has all required fields, so no migration
    # or model change is needed.
    if selected_pet_sale:
        pet_snapshot_status = CombinedPaymentSession.STATUS_PAID

        if paid_amount < final_total:
            # Do not leave this receipt snapshot as "waiting", because the
            # customer-display page only searches waiting payment sessions.
            pet_snapshot_status = CombinedPaymentSession.STATUS_CANCELLED

        CombinedPaymentSession.objects.update_or_create(
            session_key=f"pos-pet-receipt-{sale.id}",
            defaults={
                "branch": branch,
                "cashier": request.user,
                "pos_sale": sale,
                "pet_sale_id": selected_pet_sale.id,
                "total_amount": final_total,
                "pos_amount": cart_subtotal,
                "pet_amount": selected_pet_remaining,
                "status": pet_snapshot_status,
                "paid_at": timezone.now() if paid_amount >= final_total else None,
            },
        )

    if customer:
        earned_points = int(cart_subtotal)
        customer.points = int(customer.points or 0) + earned_points
        customer.total_spent = (customer.total_spent or Decimal("0.00")) + final_total
        customer.updated_by = request.user
        customer.save(update_fields=[
            "points",
            "total_spent",
            "updated_by",
            "updated_at",
        ])

    # ==================================================
    # NORMAL POS ITEMS
    # ==================================================
    for cart_item in cart_items:
        item = cart_item["item"]
        variant = cart_item["variant"]
        quantity = int(cart_item["quantity"])
        price = cart_item["price"]

        SaleItem.objects.create(
            sale=sale,
            branch=branch,
            item=item,
            variant=variant,
            quantity=quantity,
            price=price,
        )

        if not is_service_item(item):
            if not variant:
                variant = _find_best_variant_for_branch(item, branch)

            if variant:
                _deduct_selected_variant_from_branch(
                    item=item,
                    variant=variant,
                    qty=quantity,
                    user=request.user,
                    sale=sale,
                    branch=branch,
                )

    # ==================================================
    # PAYMENT RECORDS
    # ==================================================
    if cash_usd > 0:
        SalePayment.objects.create(
            sale=sale,
            method="cash_usd",
            amount=cash_usd,
            note="POS cash USD",
        )

    if cash_khr > 0:
        SalePayment.objects.create(
            sale=sale,
            method="cash_khr",
            amount=cash_khr,
            note="POS cash KHR",
        )

    if aba_usd > 0:
        SalePayment.objects.create(
            sale=sale,
            method="aba_usd",
            amount=aba_usd,
            note="POS ABA USD",
        )

    if aba_khr > 0:
        SalePayment.objects.create(
            sale=sale,
            method="aba_khr",
            amount=aba_khr,
            note="POS ABA KHR",
        )

    # ==================================================
    # COMPLETE ATTACHED PET SALE FROM POS
    # ==================================================
    pet_sale_completed_now = False
    pet_sale_partial_now = False
    telegram_sent = False

    if selected_pet_sale:
        old_paid = selected_pet_sale.paid_amount or Decimal("0.00")
        old_remaining = selected_pet_remaining

        if old_remaining < 0:
            old_remaining = Decimal("0.00")

        # If this whole POS checkout is fully paid, complete the pet sale.
        # If partial paid, product/cart money is covered first, then leftover goes to pet sale.
        if paid_amount >= final_total:
            pet_pay_amount = old_remaining
        else:
            money_available_for_pet = paid_amount - cart_subtotal

            if money_available_for_pet < 0:
                money_available_for_pet = Decimal("0.00")

            pet_pay_amount = min(old_remaining, money_available_for_pet)

        if pet_pay_amount < 0:
            pet_pay_amount = Decimal("0.00")

        if pet_pay_amount >= old_remaining and old_remaining > 0:
            try:
                from pets.views import complete_pet_sale, send_pet_sale_telegram_alert

                complete_pet_sale(
                    request=request,
                    sale=selected_pet_sale,
                    extra_paid=pet_pay_amount,
                    warranty_days=selected_pet_sale.warranty_days or 3,
                )

                send_pet_sale_telegram_alert(
                    selected_pet_sale,
                    complete_only=True,
                    first_paid_amount=old_paid,
                    final_paid_amount=pet_pay_amount,
                )

                pet_sale_completed_now = True
                telegram_sent = True

            except Exception:
                # Fallback if importing pets.views has any issue.
                selected_pet_sale.paid_amount = old_paid + pet_pay_amount
                selected_pet_sale.remaining_amount = Decimal("0.00")
                selected_pet_sale.status = "completed"

                if hasattr(selected_pet_sale, "completed_at"):
                    selected_pet_sale.completed_at = timezone.now()

                today = timezone.localdate()

                if hasattr(selected_pet_sale, "warranty_start_date"):
                    selected_pet_sale.warranty_start_date = today

                if hasattr(selected_pet_sale, "warranty_expire_date"):
                    selected_pet_sale.warranty_expire_date = today + timezone.timedelta(
                        days=selected_pet_sale.warranty_days or 3
                    )

                selected_pet_sale.save()

                if selected_pet_sale.pet:
                    selected_pet_sale.pet.status = "sold"
                    selected_pet_sale.pet.save(update_fields=["status"])

                pet_sale_completed_now = True
                telegram_sent = False

        else:
            selected_pet_sale.paid_amount = old_paid + pet_pay_amount
            sale_price = selected_pet_sale.sale_price or Decimal("0.00")
            selected_pet_sale.remaining_amount = sale_price - selected_pet_sale.paid_amount

            if selected_pet_sale.remaining_amount < 0:
                selected_pet_sale.remaining_amount = Decimal("0.00")

            if selected_pet_sale.remaining_amount <= 0:
                selected_pet_sale.status = "completed"

                if hasattr(selected_pet_sale, "completed_at"):
                    selected_pet_sale.completed_at = timezone.now()

                if selected_pet_sale.pet:
                    selected_pet_sale.pet.status = "sold"
                    selected_pet_sale.pet.save(update_fields=["status"])

                pet_sale_completed_now = True
            else:
                selected_pet_sale.status = "deposit"
                pet_sale_partial_now = True

            selected_pet_sale.save()

        request.session.pop("selected_pet_sale_id", None)
        request.session.modified = True

    # ==================================================
    # PREPARE DELIVERY
    # ==================================================
    if sale_type == "prepare_delivery":
        receiver_name = request.POST.get("delivery_receiver_name", "").strip()
        delivery_phone = request.POST.get("delivery_phone", "").strip()
        delivery_address = request.POST.get("delivery_address", "").strip()
        delivery_note = request.POST.get("delivery_note", "").strip()

        delivery_area = request.POST.get("delivery_area", "pp").strip() or "pp"
        delivery_company_id = request.POST.get("delivery_company_id", "").strip()
        customer_chat_source = request.POST.get("customer_chat_source", "").strip()
        customer_social_name = request.POST.get("customer_social_name", "").strip()

        delivery_company = None

        if delivery_company_id:
            delivery_company = DeliveryCompany.objects.filter(
                id=delivery_company_id,
                is_active=True,
            ).first()

        if not receiver_name:
            if customer:
                receiver_name = customer.name
            elif customer_name:
                receiver_name = customer_name
            elif customer_search:
                receiver_name = customer_search
            else:
                receiver_name = "Walk-in Customer"

        if not delivery_phone:
            if customer:
                delivery_phone = customer.phone
            elif customer_phone:
                delivery_phone = customer_phone
            elif customer_search:
                delivery_phone = customer_search

        if not delivery_address:
            delivery_address = "Need update address"

        if balance_amount > 0:
            payment_type = "cod_collect"
            expected_collect = balance_amount
        else:
            payment_type = "paid"
            expected_collect = Decimal("0.00")

        delivery = Delivery.objects.create(
            branch=branch,
            sale=sale,
            delivery_area=delivery_area,
            delivery_company=delivery_company,
            customer_name=receiver_name,
            phone=delivery_phone,
            location=delivery_address,
            chat_source=customer_chat_source,
            social_name=customer_social_name,
            total_price=final_total,
            payment_type=payment_type,
            expected_collect=expected_collect,
            actual_received=Decimal("0.00"),
            delivery_fee=delivery_fee,
            delivery_fee_paid=False,
            delivery_note=delivery_note or f"Created from POS Sale #{sale.id}",
            status="pending",
        )

        for cart_item in cart_items:
            variant = cart_item["variant"]

            if not variant:
                continue

            DeliveryItem.objects.create(
                delivery=delivery,
                variant=variant,
                qty=int(cart_item["quantity"]),
                unit_price=cart_item["price"],
                note=f"From POS Sale #{sale.id}",
            )

        delivery.total_price = final_total

        if balance_amount > 0:
            delivery.payment_type = "cod_collect"
            delivery.expected_collect = balance_amount
        else:
            delivery.payment_type = "paid"
            delivery.expected_collect = Decimal("0.00")

        delivery.actual_received = Decimal("0.00")
        delivery.delivery_fee = delivery_fee
        delivery.delivery_area = delivery_area
        delivery.delivery_company = delivery_company
        delivery.chat_source = customer_chat_source
        delivery.social_name = customer_social_name
        delivery.lack_amount = delivery.calculate_lack()

        delivery.save(update_fields=[
            "total_price",
            "payment_type",
            "expected_collect",
            "actual_received",
            "delivery_fee",
            "delivery_area",
            "delivery_company",
            "chat_source",
            "social_name",
            "lack_amount",
        ])

        sale.delivery_created = True
        sale.save(update_fields=["delivery_created"])

    # ==================================================
    # CLEAR CART + MESSAGES
    # ==================================================
    _save_cart(request, {})

    if pet_sale_completed_now:
        if telegram_sent:
            messages.success(
                request,
                f"Sale #{sale.id} completed. Pet sale #{selected_pet_sale.id} completed and Telegram alert sent.",
            )
        else:
            messages.success(
                request,
                f"Sale #{sale.id} completed. Pet sale #{selected_pet_sale.id} completed. Telegram alert not sent; check bot setting.",
            )

    elif pet_sale_partial_now:
        messages.warning(
            request,
            f"Sale #{sale.id} saved. Pet sale #{selected_pet_sale.id} still has balance: ${selected_pet_sale.remaining_amount:.2f}",
        )

    elif sale_type == "prepare_delivery":
        if balance_amount > 0:
            messages.warning(
                request,
                f"Sale #{sale.id} saved and delivery created. COD balance: ${balance_amount:.2f}",
            )
        else:
            messages.success(
                request,
                f"Sale #{sale.id} saved and delivery created as already paid.",
            )

    elif paid_amount <= 0:
        messages.warning(
            request,
            f"Sale #{sale.id} saved as UNPAID. Balance: ${balance_amount:.2f}",
        )

    elif paid_amount < final_total:
        messages.warning(
            request,
            f"Sale #{sale.id} saved as PARTIAL. Balance: ${balance_amount:.2f}",
        )

    elif change_amount > 0:
        messages.success(
            request,
            f"Sale #{sale.id} completed. Change: ${change_amount:.2f}",
        )

    else:
        messages.success(
            request,
            f"Sale #{sale.id} completed successfully.",
        )

    if checkout_action == "complete_print":
        return redirect("sale_receipt", pk=sale.id)

    return redirect("pos")


# ==================================================
# SALES
# ==================================================

@login_required
def sale_list(request):
    user_branch = get_user_branch(request.user)

    # Sales page shows POS walk-in sales only.
    # Prepare Delivery sales should go to Delivery page.
    sales = (
        Sale.objects
        .filter(sale_type="walk_in")
        .select_related("customer", "branch")
        .order_by("-created_at")
    )

    if not request.user.is_superuser and user_branch:
        sales = sales.filter(branch=user_branch)

    q = request.GET.get("q", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()
    status = request.GET.get("status", "").strip()
    branch_id = request.GET.get("branch", "").strip()

    if q:
        sales = sales.filter(
            Q(id__icontains=q)
            | Q(customer__name__icontains=q)
            | Q(customer__phone__icontains=q)
            | Q(branch__name__icontains=q)
        )

    if request.user.is_superuser and branch_id:
        sales = sales.filter(branch_id=branch_id)

    if date_from:
        dt_from = parse_datetime(date_from)
        if dt_from:
            sales = sales.filter(created_at__gte=dt_from)

    if date_to:
        dt_to = parse_datetime(date_to)
        if dt_to:
            sales = sales.filter(created_at__lte=dt_to)

    if status == "paid":
        sales = sales.filter(paid_amount__gte=F("total_amount"))
    elif status == "unpaid":
        sales = sales.filter(paid_amount=0)
    elif status == "partial":
        sales = sales.filter(
            paid_amount__gt=0,
            paid_amount__lt=F("total_amount"),
        )

    total_amount = (
        sales.aggregate(total=Sum("total_amount"))["total"]
        or Decimal("0.00")
    )

    total_paid = (
        sales.aggregate(total=Sum("paid_amount"))["total"]
        or Decimal("0.00")
    )

    total_balance = total_amount - total_paid

    branches = Branch.objects.filter(is_active=True).order_by("name")

    return render(request, "pos/sale_list.html", {
        "sales": sales,
        "total_amount": total_amount,
        "total_paid": total_paid,
        "total_balance": total_balance,
        "branches": branches,
        "selected_branch": branch_id,
        "current_branch": user_branch,
    })


@login_required
def sale_detail(request, pk):
    user_branch = get_user_branch(request.user)

    sale = get_object_or_404(
        Sale.objects
        .select_related("customer", "branch")
        .prefetch_related(
            "items__item",
            "items__item__item_type",
            "items__variant",
            "payments",
        ),
        pk=pk,
    )

    if (
        not request.user.is_superuser
        and user_branch
        and sale.branch_id != user_branch.id
    ):
        messages.error(request, "You do not have permission to view this sale.")
        return redirect("sale_list")

    product_total = Decimal("0.00")
    grooming_total = Decimal("0.00")
    service_total = Decimal("0.00")
    pet_total = Decimal("0.00")

    for line in sale.items.all():
        type_name = ""

        if line.item and line.item.item_type:
            type_name = line.item.item_type.name.lower().strip()

        line_total = line.total

        if "groom" in type_name:
            grooming_total += line_total
        elif "service" in type_name:
            service_total += line_total
        elif (
            "pet" in type_name
            or "dog" in type_name
            or "cat" in type_name
            or "puppy" in type_name
        ):
            pet_total += line_total
        else:
            product_total += line_total

    balance = sale.total_amount - sale.paid_amount

    return render(request, "pos/sale_detail.html", {
        "sale": sale,
        "balance": balance,
        "khr_rate": get_khr_rate(),
        "product_total": product_total,
        "grooming_total": grooming_total,
        "service_total": service_total,
        "pet_total": pet_total,
    })


@login_required
def sale_add_payment(request, pk):
    user_branch = get_user_branch(request.user)
    sale = get_object_or_404(Sale, pk=pk)

    if (
        not request.user.is_superuser
        and user_branch
        and sale.branch_id != user_branch.id
    ):
        messages.error(request, "You do not have permission to edit this sale.")
        return redirect("sale_list")

    if request.method == "POST":
        amount = money(request.POST.get("amount"))
        method = request.POST.get("method", "cash_usd")
        note = request.POST.get("note", "")

        allowed_methods = [
            "cash_usd",
            "cash_khr",
            "aba_usd",
            "aba_khr",
            "cash",
            "aba",
            "bank",
            "other",
        ]

        if method not in allowed_methods:
            method = "cash_usd"

        if amount <= 0:
            messages.error(request, "Payment amount must be greater than 0.")
            return redirect("sale_detail", pk=sale.id)

        balance = sale.total_amount - sale.paid_amount

        if amount > balance:
            sale.change_amount += amount - balance
            amount_to_add = balance
        else:
            amount_to_add = amount

        SalePayment.objects.create(
            sale=sale,
            method=method,
            amount=amount,
            note=note,
        )

        sale.paid_amount += amount_to_add
        sale.save(update_fields=["paid_amount", "change_amount"])

        messages.success(request, "Payment added successfully.")
        return redirect("sale_detail", pk=sale.id)

    return redirect("sale_detail", pk=sale.id)


# ==================================================
# SETTINGS
# ==================================================

@login_required
def pos_exchange_rate(request):
    setting, _ = POSSetting.objects.get_or_create(id=1)

    if request.method == "POST":
        rate = money(request.POST.get("exchange_rate"))

        if rate <= 0:
            messages.error(request, "Exchange rate must be greater than 0.")
            return redirect("pos_exchange_rate")

        setting.exchange_rate = rate
        setting.save(update_fields=["exchange_rate"])

        messages.success(request, "Exchange rate updated successfully.")
        return redirect("pos_exchange_rate")

    return render(request, "pos/exchange_rate.html", {
        "setting": setting,
    })


# ==================================================
# CASH COUNT
# ==================================================

@login_required
def cash_count_dashboard(request):
    selected_date = request.GET.get("date")

    if selected_date:
        count_date = selected_date
    else:
        count_date = timezone.localdate()

    current_branch = get_pos_branch(request)

    if not current_branch:
        messages.error(
            request,
            "No branch assigned. Please ask admin to set your shop.",
        )
        return redirect("pos")

    # Cash count only counts POS walk-in sales.
    # Prepare Delivery sales should be handled in Delivery page.
    sales = (
        Sale.objects
        .filter(
            branch=current_branch,
            sale_type="walk_in",
            created_at__date=count_date,
        )
        .select_related("customer", "branch")
        .prefetch_related("payments")
        .order_by("-created_at")
    )

    payments = SalePayment.objects.filter(
        sale__branch=current_branch,
        sale__sale_type="walk_in",
        sale__created_at__date=count_date,
    )

    system_cash_usd = (
        payments.filter(method="cash_usd").aggregate(total=Sum("amount"))["total"]
        or Decimal("0")
    )

    system_cash_khr = (
        payments.filter(method="cash_khr").aggregate(total=Sum("amount"))["total"]
        or Decimal("0")
    )

    system_aba_usd = (
        payments.filter(method="aba_usd").aggregate(total=Sum("amount"))["total"]
        or Decimal("0")
    )

    system_aba_khr = (
        payments.filter(method="aba_khr").aggregate(total=Sum("amount"))["total"]
        or Decimal("0")
    )

    total_sales = (
        sales.aggregate(total=Sum("total_amount"))["total"]
        or Decimal("0")
    )

    total_paid = (
        sales.aggregate(total=Sum("paid_amount"))["total"]
        or Decimal("0")
    )

    total_change = (
        sales.aggregate(total=Sum("change_amount"))["total"]
        or Decimal("0")
    )

    # This is the branch default petty cash / change float.
    # Example: BUBU TK = 100,000៛, BUBU PP = 150,000៛
    branch_float, _ = BranchCashFloat.objects.get_or_create(
        branch=current_branch,
        defaults={
            "default_change_khr": Decimal("100000"),
        },
    )

    # When a new date cash count is created,
    # it auto uses this branch's petty cash setting.
    cash_count, created = CashCount.objects.get_or_create(
        branch=current_branch,
        date=count_date,
        defaults={
            "system_cash_usd": system_cash_usd,
            "system_cash_khr": system_cash_khr,
            "system_aba_usd": system_aba_usd,
            "opening_change_khr": branch_float.default_change_khr,
        },
    )

    if request.method == "POST":
        cash_count.opening_change_khr = money(
            request.POST.get("opening_change_khr"),
            str(branch_float.default_change_khr or Decimal("100000")),
        )
        cash_count.counted_cash_usd = money(request.POST.get("counted_cash_usd"))
        cash_count.counted_cash_khr = money(request.POST.get("counted_cash_khr"))
        cash_count.counted_aba_usd = money(request.POST.get("counted_aba_usd"))
        cash_count.note = request.POST.get("note", "")
        cash_count.counted_by = request.user
        cash_count.counted_at = timezone.now()

    # Always refresh system money from sales/payment records.
    cash_count.system_cash_usd = system_cash_usd
    cash_count.system_cash_khr = system_cash_khr
    cash_count.system_aba_usd = system_aba_usd

    opening_change_khr = cash_count.opening_change_khr or branch_float.default_change_khr or Decimal("100000")
    expected_cash_khr = opening_change_khr + system_cash_khr

    cash_count.expected_cash_khr = expected_cash_khr
    cash_count.save()

    if request.method == "POST":
        return redirect(f"{request.path}?date={count_date}")

    diff_usd = cash_count.counted_cash_usd - system_cash_usd
    diff_khr = cash_count.counted_cash_khr - expected_cash_khr
    diff_aba = cash_count.counted_aba_usd - system_aba_usd

    return render(request, "pos/cash_count_dashboard.html", {
        "count_date": count_date,
        "current_branch": current_branch,
        "sales": sales,
        "cash_count": cash_count,

        "total_sales": total_sales,
        "total_paid": total_paid,
        "total_change": total_change,

        "system_cash_usd": system_cash_usd,
        "system_cash_khr": system_cash_khr,
        "system_aba_usd": system_aba_usd,
        "system_aba_khr": system_aba_khr,

        "branch_float": branch_float,
        "opening_change_khr": opening_change_khr,
        "expected_cash_khr": expected_cash_khr,

        "diff_usd": diff_usd,
        "diff_khr": diff_khr,
        "diff_aba": diff_aba,
    })

@login_required
def sale_receipt(request, pk):
    user_branch = get_user_branch(request.user)

    sale = get_object_or_404(
        Sale.objects
        .select_related("customer", "branch")
        .prefetch_related(
            "items__item",
            "items__item__item_type",
            "items__variant",
            "payments",
        ),
        pk=pk,
    )

    if (
        not request.user.is_superuser
        and user_branch
        and sale.branch_id != user_branch.id
    ):
        messages.error(request, "You do not have permission to view this receipt.")
        return redirect("sale_list")

    product_total = Decimal("0.00")
    grooming_total = Decimal("0.00")
    service_total = Decimal("0.00")
    pet_total = Decimal("0.00")
    normal_items_total = Decimal("0.00")

    for line in sale.items.all():
        type_name = ""

        if line.item and line.item.item_type:
            type_name = line.item.item_type.name.lower().strip()

        line_total = line.total
        normal_items_total += line_total

        if "groom" in type_name:
            grooming_total += line_total
        elif "service" in type_name:
            service_total += line_total
        elif (
            "pet" in type_name
            or "dog" in type_name
            or "cat" in type_name
            or "puppy" in type_name
        ):
            pet_total += line_total
        else:
            product_total += line_total

    # ==================================================
    # ATTACHED PET SALE RECEIPT BREAKDOWN
    # ==================================================
    pet_receipt_record = (
        CombinedPaymentSession.objects
        .filter(
            pos_sale=sale,
            pet_sale_id__isnull=False,
        )
        .order_by("-created_at")
        .first()
    )

    attached_pet_sale = None
    pet_full_price = Decimal("0.00")
    pet_deposit_paid = Decimal("0.00")
    pet_balance_in_pos = Decimal("0.00")

    if pet_receipt_record:
        pet_balance_in_pos = pet_receipt_record.pet_amount or Decimal("0.00")

        attached_pet_sale = (
            PetSale.objects
            .select_related("pet", "pet__breed_profile")
            .filter(id=pet_receipt_record.pet_sale_id)
            .first()
        )

    else:
        # Compatibility for receipts made before the permanent receipt link
        # was added. Reverse discount/tax to recover the original checkout
        # subtotal, then subtract normal POS items to find the pet balance.
        checkout_subtotal = (
            (sale.total_amount or Decimal("0.00"))
            + (sale.discount_amount or Decimal("0.00"))
            - (sale.tax_amount or Decimal("0.00"))
        )

        inferred_pet_balance = checkout_subtotal - normal_items_total

        if inferred_pet_balance > 0:
            pet_balance_in_pos = inferred_pet_balance

            # Find the pet sale completed closest to this POS receipt.
            # This fallback is used only for old receipts without a saved link.
            if sale.created_at:
                time_from = sale.created_at - timezone.timedelta(minutes=30)
                time_to = sale.created_at + timezone.timedelta(minutes=30)

                candidates = list(
                    PetSale.objects
                    .select_related("pet", "pet__breed_profile")
                    .filter(
                        completed_at__isnull=False,
                        completed_at__gte=time_from,
                        completed_at__lte=time_to,
                    )
                    .order_by("completed_at")[:30]
                )

                if candidates:
                    candidates.sort(
                        key=lambda pet_sale: abs(
                            (pet_sale.completed_at - sale.created_at).total_seconds()
                        )
                    )
                    attached_pet_sale = candidates[0]

    if attached_pet_sale:
        pet_full_price = (
            attached_pet_sale.sale_price
            or Decimal("0.00")
        )

        pet_deposit_paid = pet_full_price - pet_balance_in_pos

        if pet_deposit_paid < 0:
            pet_deposit_paid = Decimal("0.00")

    balance = sale.total_amount - sale.paid_amount

    return render(request, "pos/sale_receipt.html", {
        "sale": sale,
        "balance": balance,
        "product_total": product_total,
        "grooming_total": grooming_total,
        "service_total": service_total,
        "pet_total": pet_total,
        "normal_items_total": normal_items_total,
        "khr_rate": get_khr_rate(),

        # Attached pet sale
        "attached_pet_sale": attached_pet_sale,
        "pet_full_price": pet_full_price,
        "pet_deposit_paid": pet_deposit_paid,
        "pet_balance_in_pos": pet_balance_in_pos,
        "has_attached_pet": bool(
            pet_receipt_record
            or attached_pet_sale
            or pet_balance_in_pos > 0
        ),
    })

@login_required
def branch_cash_float_settings(request):
    current_branch = get_pos_branch(request)

    if not current_branch:
        messages.error(
            request,
            "No branch assigned. Please ask admin to set your shop.",
        )
        return redirect("pos")

    if request.user.is_superuser:
        branches = Branch.objects.filter(is_active=True).order_by("name")
    else:
        branches = Branch.objects.filter(id=current_branch.id)

    for branch in branches:
        BranchCashFloat.objects.get_or_create(
            branch=branch,
            defaults={
                "default_change_khr": Decimal("100000"),
            },
        )

    cash_floats = (
        BranchCashFloat.objects
        .select_related("branch", "updated_by")
        .filter(branch__in=branches)
        .order_by("branch__name")
    )

    if request.method == "POST":
        branch_id = request.POST.get("branch_id", "").strip()
        default_change_khr = money(
            request.POST.get("default_change_khr"),
            "100000",
        )
        note = request.POST.get("note", "").strip()

        if request.user.is_superuser:
            branch = Branch.objects.filter(
                id=branch_id,
                is_active=True,
            ).first()
        else:
            branch = current_branch

        if not branch:
            messages.error(request, "Invalid branch selected.")
            return redirect("branch_cash_float_settings")

        cash_float, _ = BranchCashFloat.objects.get_or_create(
            branch=branch,
            defaults={
                "default_change_khr": Decimal("100000"),
            },
        )

        cash_float.default_change_khr = default_change_khr
        cash_float.note = note
        cash_float.updated_by = request.user
        cash_float.save(update_fields=[
            "default_change_khr",
            "note",
            "updated_by",
            "updated_at",
        ])

        messages.success(
            request,
            f"Cash float updated for {branch.name}: {default_change_khr:,.0f}៛",
        )
        return redirect("branch_cash_float_settings")

    return render(request, "pos/branch_cash_float_settings.html", {
        "cash_floats": cash_floats,
        "branches": branches,
        "current_branch": current_branch,
    })

@login_required
def customer_display(request):
    current_branch = get_pos_branch(request)

    cart = _get_cart(request)
    cart_items, cart_subtotal = _build_cart_items(cart, current_branch)

    khr_rate = get_khr_rate()
    if not khr_rate or khr_rate <= 0:
        khr_rate = Decimal("4100")

    # ==================================================
    # PET SALE DISPLAY
    # ==================================================
    selected_pet_sale = None
    selected_pet_image_url = ""
    selected_pet_full_price = Decimal("0.00")
    selected_pet_paid = Decimal("0.00")
    selected_pet_remaining = Decimal("0.00")

    selected_pet_sale_id = request.session.get("selected_pet_sale_id")

    if selected_pet_sale_id:
        try:
            selected_pet_sale = (
                PetSale.objects
                .select_related("pet", "pet__breed_profile")
                .prefetch_related("photos")
                .filter(id=selected_pet_sale_id)
                .first()
            )

            if selected_pet_sale:
                selected_pet_full_price = selected_pet_sale.sale_price or Decimal("0.00")
                selected_pet_paid = selected_pet_sale.paid_amount or Decimal("0.00")

                try:
                    selected_pet_remaining = selected_pet_sale.remaining_amount or Decimal("0.00")
                except Exception:
                    selected_pet_remaining = selected_pet_full_price - selected_pet_paid

                if selected_pet_remaining < 0:
                    selected_pet_remaining = Decimal("0.00")

                first_photo = selected_pet_sale.photos.first()

                if first_photo and first_photo.photo:
                    selected_pet_image_url = first_photo.photo.url
                elif selected_pet_sale.sale_photo:
                    selected_pet_image_url = selected_pet_sale.sale_photo.url
                elif selected_pet_sale.pet and selected_pet_sale.pet.display_photo:
                    selected_pet_image_url = selected_pet_sale.pet.display_photo.url
                elif (
                    selected_pet_sale.pet
                    and selected_pet_sale.pet.breed_profile
                    and selected_pet_sale.pet.breed_profile.photo
                ):
                    selected_pet_image_url = selected_pet_sale.pet.breed_profile.photo.url

        except Exception:
            selected_pet_sale = None
            selected_pet_image_url = ""
            selected_pet_full_price = Decimal("0.00")
            selected_pet_paid = Decimal("0.00")
            selected_pet_remaining = Decimal("0.00")

    # ==================================================
    # TOTAL
    # ==================================================
    subtotal = cart_subtotal + selected_pet_remaining
    total = subtotal
    total_khr = total * Decimal(str(khr_rate))

    # ==================================================
    # ABA QR SESSION
    # ==================================================
    aba_session = None
    aba_qr_image_url = ""
    aba_qr_text = ""

    if current_branch:
        aba_session = (
            ABAPaymentSession.objects
            .filter(
                branch=current_branch,
                status=ABAPaymentSession.STATUS_WAITING,
            )
            .order_by("-created_at")
            .first()
        )

    if aba_session:
        aba_qr_image_url = aba_session.qr_image_url or ""
        aba_qr_text = aba_session.qr_text or ""

    # ==================================================
    # CUSTOMER POINTS
    # ==================================================
    customer = None

    customer_id = (
        request.session.get("selected_customer_id")
        or request.session.get("pos_customer_id")
        or request.session.get("customer_id")
    )

    customer_phone = (
        request.session.get("selected_customer_phone")
        or request.session.get("pos_customer_phone")
        or request.session.get("customer_phone")
        or ""
    )

    if customer_id:
        customer = Customer.objects.filter(id=customer_id).first()

    if not customer and customer_phone:
        customer = Customer.objects.filter(phone=customer_phone).first()

    if customer:
        customer_points = int(customer.points or 0)
    else:
        customer_points = request.session.get("customer_points", None)

    earn_points = int(total or 0)

    return render(request, "pos/customer_display.html", {
        "cart_items": cart_items,

        "subtotal": subtotal,
        "cart_subtotal": cart_subtotal,
        "total": total,
        "total_khr": total_khr,

        "current_branch": current_branch,
        "khr_rate": khr_rate,

        # ABA QR
        "aba_session": aba_session,
        "aba_qr_image_url": aba_qr_image_url,
        "aba_qr_text": aba_qr_text,

        # Customer points
        "customer": customer,
        "customer_points": customer_points,
        "earn_points": earn_points,

        # Pet sale
        "selected_pet_sale": selected_pet_sale,
        "selected_pet_image_url": selected_pet_image_url,
        "selected_pet_full_price": selected_pet_full_price,
        "selected_pet_paid": selected_pet_paid,
        "selected_pet_remaining": selected_pet_remaining,
    })

@login_required
def combined_payment_display(request):
    current_branch = get_pos_branch(request)

    session = (
        CombinedPaymentSession.objects
        .filter(
            branch=current_branch,
            status=CombinedPaymentSession.STATUS_WAITING,
        )
        .order_by("-created_at")
        .first()
    )

    return render(request, "pos/combined_payment_display.html", {
        "session": session,
        "current_branch": current_branch,
    })


@login_required
def create_aba_qr_for_display(request):
    current_branch = get_pos_branch(request)

    if not current_branch:
        messages.error(request, "No branch selected.")
        return redirect("pos")

    cart = _get_cart(request)
    cart_items, cart_subtotal = _build_cart_items(cart, current_branch)

    selected_pet_remaining = Decimal("0.00")
    selected_pet_sale_id = request.session.get("selected_pet_sale_id")

    if selected_pet_sale_id:
        selected_pet_sale = PetSale.objects.filter(id=selected_pet_sale_id).first()

        if selected_pet_sale:
            selected_pet_remaining = selected_pet_sale.remaining_amount or Decimal("0.00")

            if selected_pet_remaining <= 0:
                selected_pet_remaining = (
                    selected_pet_sale.sale_price or Decimal("0.00")
                ) - (
                    selected_pet_sale.paid_amount or Decimal("0.00")
                )

            if selected_pet_remaining < 0:
                selected_pet_remaining = Decimal("0.00")

    total = cart_subtotal + selected_pet_remaining

    if total <= 0:
        messages.error(request, "Total must be greater than 0 to create ABA QR.")
        return redirect("pos")

    # Clear old waiting QR for this branch
    ABAPaymentSession.objects.filter(
        branch=current_branch,
        status=ABAPaymentSession.STATUS_WAITING,
    ).update(status=ABAPaymentSession.STATUS_CANCELLED)

    try:
        aba_session = create_real_aba_payment(
            branch=current_branch,
            cashier=request.user,
            amount=total,
        )

        messages.success(
            request,
            f"ABA QR created for customer display: ${aba_session.amount:.2f}",
        )

    except Exception as e:
        messages.error(
            request,
            f"Cannot create ABA QR. Please check ABA setting. Error: {str(e)}",
        )

    return redirect("pos")