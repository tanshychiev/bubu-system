from decimal import Decimal

from django.db.models import Sum, F, DecimalField, ExpressionWrapper
from django.db.models.functions import Coalesce
from django.shortcuts import render
from django.utils import timezone

from inventory.models import Item, BranchStock
from customers.models import Customer
from pos.models import Sale
from pets.models import Pet, PetSale


def money(value):
    return value or Decimal("0.00")


def dashboard(request):
    today = timezone.localdate()
    first_day_this_month = today.replace(day=1)

    start_this_week = today - timezone.timedelta(days=today.weekday())
    start_last_week = start_this_week - timezone.timedelta(days=7)
    end_last_week = start_this_week - timezone.timedelta(days=1)

    # =========================
    # POS SALES
    # Your Sale model uses total_amount, not final_total
    # =========================
    all_sales = Sale.objects.all()

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

    total_sales = money(
        all_sales.aggregate(total=Coalesce(Sum("total_amount"), Decimal("0.00")))["total"]
    )

    today_sales = money(
        today_sales_qs.aggregate(total=Coalesce(Sum("total_amount"), Decimal("0.00")))["total"]
    )

    this_month_sales = money(
        month_sales_qs.aggregate(total=Coalesce(Sum("total_amount"), Decimal("0.00")))["total"]
    )

    this_week_sales = money(
        this_week_sales_qs.aggregate(total=Coalesce(Sum("total_amount"), Decimal("0.00")))["total"]
    )

    last_week_sales = money(
        last_week_sales_qs.aggregate(total=Coalesce(Sum("total_amount"), Decimal("0.00")))["total"]
    )

    today_orders = today_sales_qs.count()
    total_orders = all_sales.count()

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
        pet_sales.aggregate(total=Coalesce(Sum("sale_price"), Decimal("0.00")))["total"]
    )

    pet_total_paid = money(
        pet_sales.aggregate(total=Coalesce(Sum("paid_amount"), Decimal("0.00")))["total"]
    )

    total_balance = pet_total_amount - pet_total_paid

    # =========================
    # RECENT ORDERS
    # Make total usable in dashboard template
    # =========================
    recent_orders = list(
        all_sales.select_related("customer").order_by("-created_at")[:5]
    )

    for order in recent_orders:
        order.total = order.total_amount

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