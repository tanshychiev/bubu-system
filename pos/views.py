from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q, Sum, F, Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime


from customers.models import Customer
from inventory.models import (
    Item,
    ItemType,
    ItemVariant,
    StockMovement,
    Branch,
    BranchStock,
)
from .models import Sale, SaleItem, SalePayment, POSSetting, CashCount


# ==================================================
# BASIC HELPERS
# ==================================================

def money(value, default="0"):
    try:
        return Decimal(str(value or default))
    except (InvalidOperation, TypeError, ValueError):
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


def get_pos_branch(request):
    """
    POS branch rule:
    - normal staff: locked to user.staff_profile.branch
    - superuser: can use session branch if set
    - fallback: first active branch
    """

    if request.user.is_superuser:
        branch_id = request.session.get("pos_branch_id")

        if branch_id:
            branch = Branch.objects.filter(id=branch_id, is_active=True).first()
            if branch:
                return branch

    profile = getattr(request.user, "staff_profile", None)

    if profile and profile.branch_id:
        return profile.branch

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
        .filter(branch=branch, variant__item=item, variant__is_active=True)
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

        branch_stock = 0

        if variant:
            branch_stock = _get_branch_variant_stock(branch, variant)
        else:
            branch_stock = _get_item_branch_stock(item, branch)

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
    if is_service_item(item):
        return

    if not branch:
        raise ValueError("No branch selected for POS sale.")

    if not variant:
        raise ValueError("No variant selected for stock item.")

    stock, created = BranchStock.objects.select_for_update().get_or_create(
        branch=branch,
        variant=variant,
        defaults={"quantity": 0},
    )

    stock.quantity = int(stock.quantity or 0) - int(qty)
    stock.save(update_fields=["quantity"])

    StockMovement.objects.create(
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
# POS MAIN
# ==================================================

@login_required
def pos(request):
    current_branch = get_pos_branch(request)

    if not current_branch:
        messages.error(request, "No branch assigned. Please ask admin to set your shop.")
        return redirect("dashboard")

    raw_q = request.GET.get("q", "").strip()
    q = raw_q
    type_id = request.GET.get("type", "").strip()

    if q.upper().startswith("SKU:"):
        q = q.split(":", 1)[1].strip()

    active_variants_qs = (
        ItemVariant.objects
        .filter(is_active=True)
        .order_by("sale_price", "size", "color", "label", "id")
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

    if q:
        variant = (
            ItemVariant.objects
            .select_related("item", "item__item_type")
            .filter(item__is_active=True, is_active=True, sku__iexact=q)
            .first()
        )

        if variant:
            # ✅ Allow cashier to sell even if branch stock is 0 or negative.
            # Stock will be deducted at checkout and can become negative.
            _add_to_cart(request, variant.item, variant)
            messages.success(request, f"Added {variant.item.name} - {variant.display_name()}")
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

                # ✅ Allow cashier to sell even if branch stock is 0 or negative.
                _add_to_cart(request, exact_item, variant)
                return redirect("pos")

            if active_variants.count() == 0 or is_service_item(exact_item):
                _add_to_cart(request, exact_item, None)
                return redirect("pos")

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

    # ✅ Coming Soon = bought already, but supplier not yet received
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

    cart = _get_cart(request)
    cart_items, subtotal = _build_cart_items(cart, current_branch)

    return render(request, "pos/pos.html", {
        "items": items,
        "item_types": item_types,
        "cart_items": cart_items,
        "subtotal": subtotal,
        "discount": Decimal("0.00"),
        "tax": Decimal("0.00"),
        "total": subtotal,
        "khr_rate": get_khr_rate(),
        "selected_type": type_id,
        "q": raw_q,
        "customers": customers,
        "current_branch": current_branch,
    })

# ==================================================
# CART ACTIONS
# ==================================================

@login_required
def pos_add_cart(request, item_id):
    current_branch = get_pos_branch(request)

    if not current_branch:
        messages.error(request, "No branch assigned. Please ask admin to set your shop.")
        return redirect("pos")

    item = get_object_or_404(
        Item.objects.select_related("item_type").prefetch_related("variants"),
        id=item_id,
        is_active=True,
    )

    if is_service_item(item):
        _add_to_cart(request, item, None)
        return redirect("pos")

    active_variants = item.variants.filter(is_active=True)

    if active_variants.count() > 1:
        messages.error(request, "Please select variant first.")
        return redirect("pos")

    variant = active_variants.first()

    if not variant:
        messages.error(request, "This product has no active variant.")
        return redirect("pos")

    # ✅ Allow cashier to sell even if branch stock is 0 or negative.
    # Stock will be deducted at checkout and can become negative.
    _add_to_cart(request, item, variant)
    return redirect("pos")


@login_required
def pos_add_variant_cart(request, item_id, variant_id):
    current_branch = get_pos_branch(request)

    if not current_branch:
        messages.error(request, "No branch assigned. Please ask admin to set your shop.")
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

    # ✅ Allow cashier to sell even if branch stock is 0 or negative.
    # Stock will be deducted at checkout and can become negative.
    _add_to_cart(request, item, variant)
    return redirect("pos")


@login_required
def pos_plus_cart(request, cart_key):
    current_branch = get_pos_branch(request)
    cart = _get_cart(request)

    if cart_key in cart:
        row = cart[cart_key]
        variant_id = row.get("variant_id")
        item_id = row.get("item_id")
        current_qty = int(row.get("qty", 0))

        # ✅ Allow qty to increase even if stock becomes negative.
        cart[cart_key]["qty"] = current_qty + 1

    _save_cart(request, cart)
    return redirect("pos")


@login_required
def pos_minus_cart(request, cart_key):
    cart = _get_cart(request)

    if cart_key in cart:
        cart[cart_key]["qty"] = int(cart[cart_key].get("qty", 0)) - 1

        if cart[cart_key]["qty"] <= 0:
            del cart[cart_key]

    _save_cart(request, cart)
    return redirect("pos")


@login_required
def pos_remove_cart(request, cart_key):
    cart = _get_cart(request)
    cart.pop(cart_key, None)
    _save_cart(request, cart)
    return redirect("pos")


@login_required
def pos_clear_cart(request):
    _save_cart(request, {})
    messages.success(request, "Cart cleared")
    return redirect("pos")


# ==================================================
# CHECKOUT
# ==================================================

@login_required
@transaction.atomic
def pos_checkout(request):
    if request.method != "POST":
        return redirect("pos")

    current_branch = get_pos_branch(request)

    if not current_branch:
        messages.error(request, "No branch assigned. Please ask admin to set your shop.")
        return redirect("pos")

    cart = _get_cart(request)

    if not cart:
        messages.error(request, "Cart is empty")
        return redirect("pos")

    cart_items, subtotal = _build_cart_items(cart, current_branch)

    if not cart_items:
        messages.error(request, "Cart is invalid")
        return redirect("pos")

    for cart_item in cart_items:
        item = cart_item["item"]
        variant = cart_item["variant"]

        if is_service_item(item):
            continue

        if not variant:
            messages.error(request, f"{item.name} has no variant selected.")
            return redirect("pos")

    rate = get_khr_rate()

    cash_usd = money(request.POST.get("cash_usd"))
    cash_khr = money(request.POST.get("cash_khr"))
    aba_usd = money(request.POST.get("aba_usd"))
    aba_khr = money(request.POST.get("aba_khr"))

    discount_type = request.POST.get("discount_type", "percent")
    discount_value = money(request.POST.get("discount_value"))
    tax_type = request.POST.get("tax_type", "percent")
    tax_value = money(request.POST.get("tax_value"))

    sale_type = request.POST.get("sale_type", "walk_in")

    discount_amount = Decimal("0.00")

    if discount_value > 0:
        if discount_type == "percent":
            discount_amount = subtotal * discount_value / Decimal("100")
        else:
            discount_amount = discount_value

    if discount_amount > subtotal:
        discount_amount = subtotal

    taxable_amount = subtotal - discount_amount

    tax_amount = Decimal("0.00")

    if tax_value > 0:
        if tax_type == "percent":
            tax_amount = taxable_amount * tax_value / Decimal("100")
        else:
            tax_amount = tax_value

    final_total = taxable_amount + tax_amount

    paid_usd = cash_usd + aba_usd + (cash_khr / rate) + (aba_khr / rate)
    change_usd = paid_usd - final_total

    if paid_usd < final_total:
        messages.error(request, "Payment not enough")
        return redirect("pos")

    phone = (
        request.POST.get("customer_phone")
        or request.POST.get("phone")
        or ""
    ).strip()

    customer = None

    if phone:
        customer, _ = Customer.objects.get_or_create(
            phone=phone,
            defaults={"name": phone},
        )

    points = int(final_total // Decimal("1"))

    sale = Sale.objects.create(
        branch=current_branch,
        customer=customer,
        sale_type=sale_type,
        total_amount=final_total,
        paid_amount=paid_usd,
        change_amount=max(change_usd, Decimal("0.00")),
    )

    for cart_item in cart_items:
        item = cart_item["item"]
        variant = cart_item["variant"]
        qty = int(cart_item["quantity"])
        price = cart_item["price"]

        SaleItem.objects.create(
            sale=sale,
            branch=current_branch,
            item=item,
            variant=variant,
            quantity=qty,
            price=price,
        )

        _deduct_selected_variant_from_branch(
            item=item,
            variant=variant,
            qty=qty,
            user=request.user,
            sale=sale,
            branch=current_branch,
        )

    if cash_usd > 0:
        SalePayment.objects.create(sale=sale, method="cash_usd", amount=cash_usd)

    if cash_khr > 0:
        SalePayment.objects.create(sale=sale, method="cash_khr", amount=cash_khr)

    if aba_usd > 0:
        SalePayment.objects.create(sale=sale, method="aba_usd", amount=aba_usd)

    if aba_khr > 0:
        SalePayment.objects.create(sale=sale, method="aba_khr", amount=aba_khr)

    if customer:
        customer.points += points
        customer.total_spent += final_total
        customer.save(update_fields=["points", "total_spent"])

    _save_cart(request, {})

    if sale.sale_type == "prepare_delivery":
        messages.success(
            request,
            f"Sale #{sale.id} saved for delivery preparation.",
        )
    else:
        messages.success(
            request,
            f"Sale completed at {current_branch.name}. Change: ${max(change_usd, Decimal('0.00')):.2f} / +{points} pts",
        )

    return redirect("sale_detail", pk=sale.id)

# ==================================================
# SALES
# ==================================================

@login_required
def sale_list(request):
    sales = Sale.objects.select_related("customer", "branch").order_by("-created_at")

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

    if branch_id:
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

    total_amount = sales.aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")
    total_paid = sales.aggregate(total=Sum("paid_amount"))["total"] or Decimal("0.00")
    total_balance = total_amount - total_paid

    branches = Branch.objects.filter(is_active=True).order_by("name")

    return render(request, "pos/sale_list.html", {
        "sales": sales,
        "total_amount": total_amount,
        "total_paid": total_paid,
        "total_balance": total_balance,
        "branches": branches,
        "selected_branch": branch_id,
    })


@login_required
def sale_detail(request, pk):
    sale = get_object_or_404(
        Sale.objects
        .select_related("customer", "branch")
        .prefetch_related("items__item", "items__variant", "payments"),
        pk=pk,
    )

    balance = sale.total_amount - sale.paid_amount

    return render(request, "pos/sale_detail.html", {
        "sale": sale,
        "balance": balance,
        "khr_rate": get_khr_rate(),
    })


@login_required
def sale_add_payment(request, pk):
    sale = get_object_or_404(Sale, pk=pk)

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
            messages.error(request, "Payment amount must be greater than 0")
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

        messages.success(request, "Payment added successfully")
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
            messages.error(request, "Exchange rate must be greater than 0")
            return redirect("pos_exchange_rate")

        setting.exchange_rate = rate
        setting.save(update_fields=["exchange_rate"])

        messages.success(request, "Exchange rate updated successfully")
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

    sales = Sale.objects.filter(created_at__date=count_date).order_by("-created_at")
    payments = SalePayment.objects.filter(sale__created_at__date=count_date)

    system_cash_usd = payments.filter(method="cash_usd").aggregate(
        total=Sum("amount")
    )["total"] or Decimal("0")

    system_cash_khr = payments.filter(method="cash_khr").aggregate(
        total=Sum("amount")
    )["total"] or Decimal("0")

    system_aba_usd = payments.filter(method="aba_usd").aggregate(
        total=Sum("amount")
    )["total"] or Decimal("0")

    system_aba_khr = payments.filter(method="aba_khr").aggregate(
        total=Sum("amount")
    )["total"] or Decimal("0")

    total_sales = sales.aggregate(
        total=Sum("total_amount")
    )["total"] or Decimal("0")

    total_paid = sales.aggregate(
        total=Sum("paid_amount")
    )["total"] or Decimal("0")

    cash_count, created = CashCount.objects.get_or_create(
        date=count_date,
        defaults={
            "system_cash_usd": system_cash_usd,
            "system_cash_khr": system_cash_khr,
            "system_aba_usd": system_aba_usd,
        },
    )

    cash_count.system_cash_usd = system_cash_usd
    cash_count.system_cash_khr = system_cash_khr
    cash_count.system_aba_usd = system_aba_usd
    cash_count.save()

    if request.method == "POST":
        cash_count.counted_cash_usd = money(request.POST.get("counted_cash_usd"))
        cash_count.counted_cash_khr = money(request.POST.get("counted_cash_khr"))
        cash_count.counted_aba_usd = money(request.POST.get("counted_aba_usd"))
        cash_count.note = request.POST.get("note", "")
        cash_count.counted_by = request.user
        cash_count.counted_at = timezone.now()
        cash_count.save()

        return redirect(f"{request.path}?date={count_date}")

    diff_usd = cash_count.counted_cash_usd - system_cash_usd
    diff_khr = cash_count.counted_cash_khr - system_cash_khr
    diff_aba = cash_count.counted_aba_usd - system_aba_usd

    return render(request, "pos/cash_count_dashboard.html", {
        "count_date": count_date,
        "sales": sales,
        "cash_count": cash_count,
        "total_sales": total_sales,
        "total_paid": total_paid,
        "system_cash_usd": system_cash_usd,
        "system_cash_khr": system_cash_khr,
        "system_aba_usd": system_aba_usd,
        "system_aba_khr": system_aba_khr,
        "diff_usd": diff_usd,
        "diff_khr": diff_khr,
        "diff_aba": diff_aba,
    })