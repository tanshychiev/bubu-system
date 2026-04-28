import json
import base64
from io import BytesIO
from decimal import Decimal, InvalidOperation

import barcode
from barcode.writer import ImageWriter

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from .forms import (
    BranchForm,
    ItemForm,
    ItemTypeForm,
    ItemVariantForm,
    StockMovementForm,
)
from .models import (
    Branch,
    Item,
    ItemType,
    ItemVariant,
    StockMovement,
    VariantEditHistory,
)


def can_manage_inventory(user):
    return user.is_authenticated and (user.is_staff or user.is_superuser)


def can_view_cost_price(user):
    return user.is_authenticated and (
        user.is_superuser or user.has_perm("inventory.can_view_cost_price")
    )


def can_edit_cost_price(user):
    return user.is_authenticated and (
        user.is_superuser or user.has_perm("inventory.can_edit_cost_price")
    )


def money(value, default="0"):
    try:
        return Decimal(str(value or default))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def snapshot_variant(variant):
    return {
        "sku": variant.sku or "",
        "color": variant.color or "",
        "size": variant.size or "",
        "label": variant.label or "",
        "quantity": variant.quantity,
        "cost_price": variant.cost_price,
        "sale_price": variant.sale_price,
        "is_active": variant.is_active,
        "image": variant.image.name if variant.image else "",
    }


def record_variant_edit_history(variant, user, before, after):
    fields = [
        "sku",
        "color",
        "size",
        "label",
        "quantity",
        "cost_price",
        "sale_price",
        "is_active",
        "image",
    ]

    for field in fields:
        old_value = before.get(field, "")
        new_value = after.get(field, "")

        if str(old_value) != str(new_value):
            VariantEditHistory.objects.create(
                variant=variant,
                edited_by=user,
                field_name=field,
                old_value=str(old_value),
                new_value=str(new_value),
            )


@login_required
def item_list(request):
    q = request.GET.get("q", "").strip()
    type_id = request.GET.get("type", "").strip()

    items = (
        Item.objects
        .prefetch_related("variants")
        .select_related("item_type")
        .order_by("name")
    )

    item_types = ItemType.objects.filter(is_active=True).order_by("name")

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

    return render(request, "inventory/item_list.html", {
        "items": items,
        "item_types": item_types,
        "selected_type": type_id,
        "can_manage_inventory": can_manage_inventory(request.user),
        "can_view_cost_price": can_view_cost_price(request.user),
        "can_edit_cost_price": can_edit_cost_price(request.user),
    })


@login_required
def item_type_create(request):
    if not can_manage_inventory(request.user):
        messages.error(request, "You do not have permission.")
        return redirect("item_list")

    form = ItemTypeForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Type created successfully.")
        return redirect("item_list")

    return render(request, "inventory/item_type_form.html", {
        "form": form,
        "title": "Create Type",
    })


@login_required
def item_create(request):
    if not can_manage_inventory(request.user):
        messages.error(request, "You do not have permission.")
        return redirect("item_list")

    can_price = can_edit_cost_price(request.user)

    form = ItemForm(
        request.POST or None,
        request.FILES or None,
        can_edit_price=can_price,
    )

    if request.method == "POST" and form.is_valid():
        item = form.save(commit=False)

        if not can_price:
            item.cost_price = Decimal("0.00")
            item.sale_price = Decimal("0.00")

        item.save()
        messages.success(request, "Item created successfully.")
        return redirect("item_detail", pk=item.pk)

    return render(request, "inventory/item_form.html", {
        "form": form,
        "title": "Create Item",
        "can_edit_cost_price": can_price,
    })


@login_required
def item_detail(request, pk):
    item = get_object_or_404(
        Item.objects.select_related("item_type").prefetch_related("variants"),
        pk=pk,
    )

    return render(request, "inventory/item_detail.html", {
        "item": item,
        "can_manage_inventory": can_manage_inventory(request.user),
        "can_view_cost_price": can_view_cost_price(request.user),
        "can_edit_cost_price": can_edit_cost_price(request.user),
    })


@login_required
def item_edit(request, pk):
    if not can_manage_inventory(request.user):
        messages.error(request, "You do not have permission.")
        return redirect("item_list")

    item = get_object_or_404(Item.objects.prefetch_related("variants"), pk=pk)
    can_price = can_edit_cost_price(request.user)

    old_cost_price = item.cost_price
    old_sale_price = item.sale_price

    form = ItemForm(
        request.POST or None,
        request.FILES or None,
        instance=item,
        can_edit_price=can_price,
    )

    if request.method == "POST" and form.is_valid():
        item = form.save(commit=False)

        if not can_price:
            item.cost_price = old_cost_price
            item.sale_price = old_sale_price

        item.save()

        default_variant = item.variants.filter(label="Default").first()

        if default_variant:
            changed_fields = []

            if default_variant.cost_price <= 0 and item.cost_price > 0:
                default_variant.cost_price = item.cost_price
                changed_fields.append("cost_price")

            if default_variant.sale_price <= 0 and item.sale_price > 0:
                default_variant.sale_price = item.sale_price
                changed_fields.append("sale_price")

            if changed_fields:
                default_variant.save(update_fields=changed_fields)

        messages.success(request, "Item updated successfully.")
        return redirect("item_detail", pk=item.pk)

    return render(request, "inventory/item_form.html", {
        "form": form,
        "title": "Edit Item",
        "can_edit_cost_price": can_price,
    })


@login_required
def item_delete(request, pk):
    if not can_manage_inventory(request.user):
        messages.error(request, "You do not have permission.")
        return redirect("item_list")

    item = get_object_or_404(Item, pk=pk)

    if request.method == "POST":
        item.delete()
        messages.success(request, "Item deleted successfully.")
        return redirect("item_list")

    return render(request, "inventory/item_confirm_delete.html", {
        "item": item,
    })


@login_required
def item_variant_create(request, pk):
    if not can_manage_inventory(request.user):
        messages.error(request, "You do not have permission.")
        return redirect("item_list")

    item = get_object_or_404(Item, pk=pk)
    can_price = can_edit_cost_price(request.user)

    form = ItemVariantForm(
        request.POST or None,
        request.FILES or None,
        can_edit_cost_price=can_price,
        can_edit_price=can_price,
        initial={
            "cost_price": item.cost_price,
            "sale_price": item.sale_price,
        } if request.method != "POST" else None,
    )

    if request.method == "POST" and form.is_valid():
        variant = form.save(commit=False)
        variant.item = item

        if not can_price:
            variant.cost_price = item.cost_price
            variant.sale_price = item.sale_price
        else:
            if variant.cost_price <= 0 and item.cost_price > 0:
                variant.cost_price = item.cost_price

            if variant.sale_price <= 0 and item.sale_price > 0:
                variant.sale_price = item.sale_price

        variant.save()
        messages.success(request, "Variant created successfully.")
        return redirect("item_detail", pk=item.pk)

    return render(request, "inventory/item_variant_form.html", {
        "form": form,
        "item": item,
        "title": "Create Variant",
        "can_edit_cost_price": can_price,
    })


@login_required
def item_variant_edit(request, pk, variant_id):
    if not can_manage_inventory(request.user):
        messages.error(request, "You do not have permission.")
        return redirect("item_list")

    item = get_object_or_404(Item, pk=pk)
    variant = get_object_or_404(ItemVariant, pk=variant_id, item=item)

    can_price = can_edit_cost_price(request.user)
    before = snapshot_variant(variant)

    old_cost_price = variant.cost_price
    old_sale_price = variant.sale_price

    form = ItemVariantForm(
        request.POST or None,
        request.FILES or None,
        instance=variant,
        can_edit_cost_price=can_price,
        can_edit_price=can_price,
    )

    if request.method == "POST" and form.is_valid():
        variant = form.save(commit=False)

        if not can_price:
            variant.cost_price = old_cost_price
            variant.sale_price = old_sale_price

        variant.save()

        after = snapshot_variant(variant)
        record_variant_edit_history(variant, request.user, before, after)

        messages.success(request, "Variant updated successfully.")
        return redirect("item_detail", pk=item.pk)

    histories = variant.edit_histories.select_related("edited_by")[:30]

    return render(request, "inventory/item_variant_form.html", {
        "form": form,
        "item": item,
        "variant": variant,
        "histories": histories,
        "title": "Edit Variant",
        "can_edit_cost_price": can_price,
    })


@login_required
def item_variant_delete(request, pk, variant_id):
    if not can_manage_inventory(request.user):
        messages.error(request, "You do not have permission.")
        return redirect("item_list")

    item = get_object_or_404(Item, pk=pk)
    variant = get_object_or_404(ItemVariant, pk=variant_id, item=item)

    if request.method == "POST":
        variant_name = variant.display_name()
        variant.delete()
        messages.success(request, f"Variant {variant_name} deleted successfully.")
        return redirect("item_detail", pk=item.pk)

    return render(request, "inventory/item_variant_confirm_delete.html", {
        "item": item,
        "variant": variant,
    })


@login_required
def stock_movement(request, pk):
    if not can_manage_inventory(request.user):
        messages.error(request, "You do not have permission.")
        return redirect("item_list")

    item = get_object_or_404(Item.objects.prefetch_related("variants"), pk=pk)
    can_cost = can_edit_cost_price(request.user)

    form = StockMovementForm(
        request.POST or None,
        item=item,
        can_edit_cost_price=can_cost,
    )

    if request.method == "POST" and form.is_valid():
        movement = form.save(commit=False)
        movement.item = item
        movement.created_by = request.user

        if movement.quantity <= 0:
            messages.error(request, "Quantity must be greater than 0.")
            return redirect("stock_movement", pk=item.pk)

        if movement.movement_type in ["out", "sale"]:
            if movement.variant and movement.quantity > movement.variant.quantity:
                messages.error(request, "Not enough stock.")
                return redirect("stock_movement", pk=item.pk)

        movement.save()
        messages.success(request, "Stock updated successfully.")
        return redirect("item_detail", pk=item.pk)

    movements = item.stock_movements.select_related("variant").order_by("-created_at")[:30]

    return render(request, "inventory/stock_movement.html", {
        "item": item,
        "form": form,
        "movements": movements,
        "can_edit_cost_price": can_cost,
    })


@login_required
def variant_stock_movement(request, variant_id):
    if not can_manage_inventory(request.user):
        messages.error(request, "You do not have permission.")
        return redirect("item_list")

    variant = get_object_or_404(
        ItemVariant.objects.select_related("item"),
        pk=variant_id,
    )
    item = variant.item
    can_cost = can_edit_cost_price(request.user)

    if request.method == "POST":
        movement_type = request.POST.get("movement_type", "in")
        quantity = int(request.POST.get("quantity") or 0)
        note = request.POST.get("note", "")

        if can_cost:
            cost_price = money(request.POST.get("cost_price"))
        else:
            cost_price = variant.cost_price or item.cost_price

        if movement_type not in ["in", "out", "adjust"]:
            messages.error(request, "Invalid stock type.")
            return redirect("variant_stock_movement", variant_id=variant.id)

        if quantity <= 0:
            messages.error(request, "Quantity must be greater than 0.")
            return redirect("variant_stock_movement", variant_id=variant.id)

        if movement_type == "out" and quantity > variant.quantity:
            messages.error(request, "Not enough stock.")
            return redirect("variant_stock_movement", variant_id=variant.id)

        StockMovement.objects.create(
            item=item,
            variant=variant,
            movement_type=movement_type,
            quantity=quantity,
            cost_price=cost_price,
            note=note,
            created_by=request.user,
        )

        messages.success(request, "Variant stock updated successfully.")
        return redirect("item_detail", pk=item.id)

    movements = variant.stock_movements.order_by("-created_at")[:30]

    return render(request, "inventory/variant_stock_movement.html", {
        "item": item,
        "variant": variant,
        "movements": movements,
        "can_edit_cost_price": can_cost,
    })


@login_required
@require_GET
def variant_search_api(request):
    if not can_manage_inventory(request.user):
        return JsonResponse({"results": []})

    q = request.GET.get("q", "").strip()

    variants = (
        ItemVariant.objects
        .select_related("item", "item__item_type")
        .filter(is_active=True)
    )

    if q:
        variants = variants.filter(
            Q(sku__icontains=q)
            | Q(item__name__icontains=q)
            | Q(item__brand__icontains=q)
            | Q(color__icontains=q)
            | Q(size__icontains=q)
            | Q(label__icontains=q)
        )

    variants = variants.order_by("item__name", "color", "size", "label")[:20]

    results = []

    for variant in variants:
        image_url = ""

        if variant.image:
            image_url = variant.image.url
        elif variant.item.image:
            image_url = variant.item.image.url

        results.append({
            "id": variant.id,
            "sku": variant.sku or "",
            "item_name": variant.item.name,
            "brand": variant.item.brand or "",
            "type": variant.item.item_type.name if variant.item.item_type else "",
            "type_emoji": variant.item.item_type.emoji if variant.item.item_type else "📦",
            "color": variant.color or "",
            "size": variant.size or "",
            "label": variant.label or "",
            "display": variant.display_name(),
            "stock": variant.quantity,
            "unit": variant.item.get_unit_display(),
            "cost_price": str(variant.cost_price),
            "sale_price": str(variant.sale_price),
            "image": image_url,
        })

    return JsonResponse({"results": results})


@login_required
def stock_batch_in(request):
    if not can_manage_inventory(request.user):
        messages.error(request, "You do not have permission.")
        return redirect("item_list")

    can_cost = can_edit_cost_price(request.user)

    if request.method == "POST":
        rows_json = request.POST.get("rows_json", "[]")

        try:
            rows = json.loads(rows_json)
        except json.JSONDecodeError:
            messages.error(request, "Invalid stock rows.")
            return redirect("stock_batch_in")

        saved_count = 0

        for row in rows:
            variant_id = row.get("variant_id")
            qty_raw = row.get("quantity") or 0
            cost_raw = row.get("cost_price") or "0"
            note = row.get("note", "").strip()

            try:
                qty = int(qty_raw)
            except Exception:
                continue

            if not variant_id or qty <= 0:
                continue

            variant = (
                ItemVariant.objects
                .select_related("item")
                .filter(id=variant_id)
                .first()
            )

            if not variant:
                continue

            if can_cost:
                cost_price = money(cost_raw)
            else:
                cost_price = variant.cost_price or variant.item.cost_price

            StockMovement.objects.create(
                item=variant.item,
                variant=variant,
                movement_type="in",
                quantity=qty,
                cost_price=cost_price,
                note=note or "Batch stock in",
                created_by=request.user,
            )

            saved_count += 1

        if saved_count:
            messages.success(request, f"{saved_count} stock rows saved successfully.")
            return redirect("item_list")

        messages.error(request, "No valid stock rows to save.")
        return redirect("stock_batch_in")

    return render(request, "inventory/stock_batch_in.html", {
        "can_edit_cost_price": can_cost,
    })


@login_required
def variant_barcode_label(request, variant_id):
    if not can_manage_inventory(request.user):
        messages.error(request, "You do not have permission.")
        return redirect("item_list")

    variant = get_object_or_404(
        ItemVariant.objects.select_related("item", "item__item_type"),
        pk=variant_id,
    )

    if not variant.sku:
        variant.save()

    barcode_class = barcode.get_barcode_class("code128")
    barcode_obj = barcode_class(variant.sku, writer=ImageWriter())

    buffer = BytesIO()
    barcode_obj.write(buffer, options={
        "module_height": 10,
        "module_width": 0.35,
        "font_size": 8,
        "text_distance": 2,
        "quiet_zone": 2,
    })

    barcode_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

    return render(request, "inventory/barcode_label.html", {
        "variant": variant,
        "item": variant.item,
        "barcode_base64": barcode_base64,
    })


@login_required
def branch_list(request):
    if not request.user.is_staff:
        messages.error(request, "Only staff can manage shops.")
        return redirect("dashboard")

    branches = Branch.objects.all().order_by("name")

    if request.method == "POST":
        branch_id = request.POST.get("branch_id")
        name = request.POST.get("name", "").strip()
        is_active = request.POST.get("is_active") == "on"

        if not name:
            messages.error(request, "Shop name is required.")
            return redirect("branch_list")

        if branch_id:
            branch = get_object_or_404(Branch, id=branch_id)
            branch.name = name
            branch.is_active = is_active
            branch.save(update_fields=["name", "is_active"])
            messages.success(request, "Shop updated successfully.")
        else:
            Branch.objects.create(
                name=name,
                is_active=is_active,
            )
            messages.success(request, "Shop created successfully.")

        return redirect("branch_list")

    return render(request, "inventory/branch_list.html", {
        "branches": branches,
    })


@login_required
@require_POST
def branch_delete(request, pk):
    if not request.user.is_staff:
        messages.error(request, "Only staff can delete shops.")
        return redirect("branch_list")

    branch = get_object_or_404(Branch, pk=pk)
    branch.delete()
    messages.success(request, "Shop deleted successfully.")
    return redirect("branch_list")


@login_required
@require_POST
def branch_toggle(request, pk):
    if not request.user.is_staff:
        return JsonResponse({"success": False}, status=403)

    branch = get_object_or_404(Branch, pk=pk)
    branch.is_active = request.POST.get("status") == "true"
    branch.save(update_fields=["is_active"])

    return JsonResponse({
        "success": True,
        "is_active": branch.is_active,
    })