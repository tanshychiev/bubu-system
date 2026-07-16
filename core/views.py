from decimal import Decimal, InvalidOperation
import calendar

from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.shortcuts import render
from django.utils import timezone

from inventory.models import Item, BranchStock
from customers.models import Customer
from pos.models import Sale
from pets.models import Pet, PetSale


MONEY_PLACES = Decimal("0.01")


def money(value):
    """
    Always return a Decimal with exactly two decimal places.
    Example: 59.9500000000000 becomes Decimal("59.95").
    """
    try:
        return Decimal(str(value or "0")).quantize(MONEY_PLACES)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00")


def sale_amount(queryset):
    """Return the summed POS total_amount for a Sale queryset."""
    result = queryset.aggregate(
        total=Coalesce(Sum("total_amount"), Decimal("0.00"))
    )["total"]
    return money(result)


def dashboard(request):
    today = timezone.localdate()
    first_day_this_month = today.replace(day=1)

    start_this_week = today - timezone.timedelta(days=today.weekday())
    start_last_week = start_this_week - timezone.timedelta(days=7)
    end_last_week = start_this_week - timezone.timedelta(days=1)

    # =========================
    # SALES PERIOD FILTER
    # Default: today
    # Options: today, yesterday, or a selected month
    # =========================
    selected_period = request.GET.get("period", "today").strip().lower()
    selected_month_value = request.GET.get("month", "").strip()

    if selected_period == "yesterday":
        selected_date = today - timezone.timedelta(days=1)
        selected_sales_qs = Sale.objects.filter(created_at__date=selected_date)
        selected_period_label = "Yesterday"

    elif selected_period == "month" and selected_month_value:
        try:
            selected_year, selected_month = map(int, selected_month_value.split("-"))
            month_start = today.replace(
                year=selected_year,
                month=selected_month,
                day=1,
            )
            last_day = calendar.monthrange(selected_year, selected_month)[1]
            month_end = month_start.replace(day=last_day)

            selected_sales_qs = Sale.objects.filter(
                created_at__date__gte=month_start,
                created_at__date__lte=month_end,
            )
            selected_period_label = month_start.strftime("%B %Y")
        except (TypeError, ValueError):
            selected_period = "today"
            selected_month_value = today.strftime("%Y-%m")
            selected_sales_qs = Sale.objects.filter(created_at__date=today)
            selected_period_label = "Today"

    else:
        selected_period = "today"
        selected_month_value = today.strftime("%Y-%m")
        selected_sales_qs = Sale.objects.filter(created_at__date=today)
        selected_period_label = "Today"

    # =========================
    # POS SALES
    # =========================
    all_sales = Sale.objects.select_related("branch")
    selected_sales_qs = selected_sales_qs.select_related("branch")

    today_sales_qs = all_sales.filter(created_at__date=today)

    month_sales_qs = all_sales.filter(
        created_at__date__gte=first_day_this_month,
        created_at__date__lte=today,
    )

    this_week_sales_qs = all_sales.filter(
        created_at__date__gte=start_this_week,
        created_at__date__lte=today,
    )

    last_week_sales_qs = all_sales.filter(
        created_at__date__gte=start_last_week,
        created_at__date__lte=end_last_week,
    )

    total_sales = sale_amount(all_sales)
    today_sales = sale_amount(today_sales_qs)
    this_month_sales = sale_amount(month_sales_qs)
    this_week_sales = sale_amount(this_week_sales_qs)
    last_week_sales = sale_amount(last_week_sales_qs)

    today_orders = today_sales_qs.count()
    total_orders = all_sales.count()

    # =========================
    # BUBU SALES BY BRANCH
    # Sale.branch is the branch relationship.
    # icontains keeps it compatible with names such as:
    # "BUBU STM" / "STM" and "BUBU SENSOK" / "SENSOK".
    # =========================
    selected_total_sales = sale_amount(selected_sales_qs)

    stm_selected_sales = sale_amount(
        selected_sales_qs.filter(branch__name__icontains="STM")
    )

    sensok_selected_sales = sale_amount(
        selected_sales_qs.filter(branch__name__icontains="SENSOK")
    )

    # =========================
    # PRODUCTS / CUSTOMERS
    # =========================
    total_products = Item.objects.count()
    total_customers = Customer.objects.count()

    # =========================
    # PET STOCK
    # =========================
    total_pets = Pet.objects.count()
    in_stock_pets = Pet.objects.filter(status="in_stock").count()
    dog_count = Pet.objects.filter(pet_type="dog").count()
    cat_count = Pet.objects.filter(pet_type="cat").count()

    # =========================
    # PET SALES
    # =========================
    pet_sales = PetSale.objects.all()

    today_pet_sales = pet_sales.filter(created_at__date=today).count()
    preorder_count = pet_sales.filter(sale_kind="preorder").count()
    instock_pet_sale_count = pet_sales.filter(sale_kind="in_stock").count()

    pet_total_amount = money(
        pet_sales.aggregate(
            total=Coalesce(Sum("sale_price"), Decimal("0.00"))
        )["total"]
    )

    pet_total_paid = money(
        pet_sales.aggregate(
            total=Coalesce(Sum("paid_amount"), Decimal("0.00"))
        )["total"]
    )

    total_balance = money(pet_total_amount - pet_total_paid)

    # =========================
    # RECENT ORDERS
    # =========================
    recent_orders = list(
        all_sales.select_related("customer").order_by("-created_at")[:5]
    )

    for order in recent_orders:
        order.total = money(order.total_amount)

    # =========================
    # LOW STOCK
    # =========================
    low_stock_items = []

    try:
        low_stock_items = list(
            BranchStock.objects
            .select_related("variant", "branch")
            .filter(quantity__lte=3)
            .order_by("quantity")[:6]
        )

        for stock in low_stock_items:
            if hasattr(stock, "variant") and stock.variant:
                stock.name = stock.variant.label or stock.variant.item.name
            else:
                stock.name = "Low stock item"

            stock.stock = stock.quantity

    except Exception:
        low_stock_items = []

    context = {
        # top stats
        "total_products": total_products,
        "total_sales": total_sales,
        "total_orders": total_orders,
        "total_customers": total_customers,

        # selected sales period
        "selected_period": selected_period,
        "selected_period_label": selected_period_label,
        "selected_month_value": selected_month_value,
        "selected_total_sales": selected_total_sales,
        "stm_selected_sales": stm_selected_sales,
        "sensok_selected_sales": sensok_selected_sales,

        # today / month
        "today_sales": today_sales,
        "today_orders": today_orders,
        "today_pet_sales": today_pet_sales,
        "this_month_sales": this_month_sales,

        # pet stock
        "total_pets": total_pets,
        "in_stock_pets": in_stock_pets,
        "dog_count": dog_count,
        "cat_count": cat_count,

        # pet sale
        "preorder_count": preorder_count,
        "instock_pet_sale_count": instock_pet_sale_count,

        # chart / money
        "this_week_sales": this_week_sales,
        "last_week_sales": last_week_sales,
        "total_balance": total_balance,

        # lists
        "recent_orders": recent_orders,
        "low_stock_items": low_stock_items,
    }

    return render(request, "core/dashboard.html", context)