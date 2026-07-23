import json
import base64
from io import BytesIO
from decimal import Decimal, InvalidOperation

import barcode
from barcode.writer import ImageWriter

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.db.models import Prefetch, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from core.cost_access import can_edit_cost, can_view_cost, is_owner

from .forms import (
    BranchForm,
    ItemForm,
    ItemTypeForm,
    ItemVariantForm,
    StockMovementForm,
    UnitOptionForm,
)

from .models import (
    Branch,
    BranchStock,
    Item,
    ItemType,
    ItemVariant,
    StockMovement,
    VariantEditHistory,
    ItemEditHistory,
    UnitOption,
)


# ==================================================
# PERMISSION HELPERS
# ==================================================

def _is_staff_inventory_user(user):
    """
    BUBU has two working roles:
    - Owner/Admin
    - Staff

    Staff must be able to add inventory records and create item types.
    Cost visibility remains controlled separately by core.cost_access.
    """
    if not user or not user.is_authenticated:
        return False

    return user.groups.filter(name__iexact="Staff").exists()


def can_manage_inventory(user):
    """
    Allow inventory work without connecting it to cost visibility.

    This honors Django role permissions and also supports the BUBU Staff
    group directly. Owner/Admin always has access.
    """
    if not user or not user.is_authenticated:
        return False

    if is_owner(user):
        return True

    if _is_staff_inventory_user(user):
        return True

    return any([
        user.has_perm("inventory.add_item"),
        user.has_perm("inventory.change_item"),
        user.has_perm("inventory.add_itemvariant"),
        user.has_perm("inventory.change_itemvariant"),
        user.has_perm("inventory.add_stockmovement"),
        user.has_perm("inventory.add_itemtype"),
    ])


def can_create_inventory_type(user):
    """
    Staff may create a new type, but deleting types, managing units and
    opening Control Center remain Owner/Admin-only.
    """
    if not user or not user.is_authenticated:
        return False

    return (
        is_owner(user)
        or _is_staff_inventory_user(user)
        or user.has_perm("inventory.add_itemtype")
    )


def can_manage_inventory_settings(user):
    return is_owner(user)


def can_view_cost_price(user):
    return can_view_cost(user)


def can_edit_cost_price(user):
    return can_edit_cost(user)


# ==================================================
# BASIC HELPERS
# ==================================================

def money(value, default="0"):
    try:
        return Decimal(str(value or default))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def get_user_branch(user):
    profile = getattr(user, "staff_profile", None)

    if profile and profile.branch_id:
        return profile.branch

    return None


def get_selected_branch(request):
    """
    Branch rule:
    - Superuser/Admin can choose branch using ?branch=ID or POST branch
    - Normal staff/cashier is locked to StaffProfile.branch
    """
    user_branch = get_user_branch(request.user)

    if request.user.is_superuser:
        branch_id = request.POST.get("branch") or request.GET.get("branch")

        if branch_id:
            branch = Branch.objects.filter(
                id=branch_id,
                is_active=True,
            ).first()

            if branch:
                return branch

        return Branch.objects.filter(is_active=True).order_by("id").first()

    return user_branch


def get_variant_branch_qty(variant, branch):
    if not variant or not branch:
        return 0

    stock = BranchStock.objects.filter(
        branch=branch,
        variant=variant,
    ).first()

    if not stock:
        return 0

    return int(stock.quantity or 0)


def get_item_branch_qty(item, branch):
    if not item or not branch:
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


def get_all_branch_stock_for_variant(variant):
    return (
        BranchStock.objects
        .filter(variant=variant)
        .select_related("branch")
        .order_by("branch__name")
    )


def delete_model_image(instance, field_name="image"):
    """
    Delete image file and clear model image field.
    Used by item_form.html, item_variant_form.html, and control center.
    """
    image_field = getattr(instance, field_name, None)

    if image_field:
        image_field.delete(save=False)
        setattr(instance, field_name, None)


def seed_default_units():
    """
    Create default units if UnitOption is empty.
    Keeps Item.unit safe because Item.unit is still CharField.
    """
    if UnitOption.objects.exists():
        return

    default_units = [
        ("piece", "Piece", "📦"),
        ("bottle", "Bottle", "🧴"),
        ("ml", "ML", "💧"),
        ("g", "Gram", "⚖️"),
        ("kg", "KG", "⚖️"),
        ("pack", "Pack", "🎁"),
        ("box", "Box", "📦"),
        ("service", "Service", "🎀"),
        ("pet", "Pet", "🐶"),
    ]

    for code, name, emoji in default_units:
        UnitOption.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "emoji": emoji,
                "is_active": True,
            },
        )


# ==================================================
# VARIANT HISTORY HELPERS
# ==================================================

def snapshot_variant(variant):
    return {
        "sku": variant.sku or "",
        "color": variant.color or "",
        "size": variant.size or "",
        "label": variant.label or "",
        "quantity": getattr(variant, "quantity", 0),
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


# ==================================================
# ITEM HISTORY HELPERS
# ==================================================

def snapshot_item(item):
    return {
        "name": item.name or "",
        "brand": item.brand or "",
        "item_type": item.item_type.name if item.item_type else "",
        "unit": item.unit or "",
        "cost_price": item.cost_price,
        "sale_price": item.sale_price,
        "is_active": item.is_active,
        "image": item.image.name if item.image else "",
    }


def record_item_edit_history(item, user, before, after):
    fields = [
        "name",
        "brand",
        "item_type",
        "unit",
        "cost_price",
        "sale_price",
        "is_active",
        "image",
    ]

    for field in fields:
        old_value = before.get(field, "")
        new_value = after.get(field, "")

        if str(old_value) != str(new_value):
            ItemEditHistory.objects.create(
                item=item,
                edited_by=user,
                field_name=field,
                old_value=str(old_value),
                new_value=str(new_value),
            )


# ==================================================
# ITEM LIST
# ==================================================

@login_required
def item_list(request):
    q = request.GET.get("q", "").strip()
    type_id = request.GET.get("type", "").strip()

    current_branch = get_selected_branch(request)
    branches = Branch.objects.filter(is_active=True).order_by("name")

    variant_qs = ItemVariant.objects.order_by("sort_order", "id")

    items = (
        Item.objects
        .filter(is_active=True)
        .select_related("item_type")
        .prefetch_related(Prefetch("variants", queryset=variant_qs))
        .order_by("name", "id")
    )

    item_types = ItemType.objects.filter(is_active=True).order_by("name")

    if q:
        # Text search should search the whole inventory. Do not keep an old
        # category filter active, because that was causing valid items to show
        # as "No items found".
        items = items.filter(
            Q(name__icontains=q)
            | Q(brand__icontains=q)
            | Q(item_type__name__icontains=q)
            | Q(variants__sku__icontains=q)
            | Q(variants__color__icontains=q)
            | Q(variants__size__icontains=q)
            | Q(variants__label__icontains=q)
        ).distinct()
        type_id = ""
    elif type_id:
        items = items.filter(item_type_id=type_id)

    items = list(items)

    for item in items:
        item.branch_stock_total = get_item_branch_qty(item, current_branch)

        for variant in item.variants.all():
            variant.branch_stock_qty = get_variant_branch_qty(
                variant,
                current_branch,
            )

    return render(request, "inventory/item_list.html", {
        "items": items,
        "item_types": item_types,
        "q": q,
        "selected_type": type_id,
        "q": q,
        "current_branch": current_branch,
        "branches": branches,
        "can_manage_inventory": can_manage_inventory(request.user),
        "can_create_inventory_type": can_create_inventory_type(request.user),
        "can_manage_inventory_settings": can_manage_inventory_settings(request.user),
        "can_view_cost_price": can_view_cost_price(request.user),
        "can_edit_cost_price": can_edit_cost_price(request.user),
    })


# ==================================================
# INVENTORY CONTROL CENTER
# ==================================================

@login_required
def inventory_control_center(request):
    """
    Admin/control page for:
    - Create type
    - Rename/hide/delete type
    - Create unit
    - Rename/hide/delete unit
    - Search/edit item
    - Record item edit history
    """
    if not can_manage_inventory_settings(request.user):
        messages.error(request, "Only Owner/Admin can open inventory settings.")
        return redirect("item_list")

    seed_default_units()

    type_form = ItemTypeForm(prefix="type")
    unit_form = UnitOptionForm(prefix="unit")

    if request.method == "POST":
        action = request.POST.get("action", "")

        # -------------------------
        # CREATE TYPE
        # -------------------------
        if action == "create_type":
            type_form = ItemTypeForm(request.POST, prefix="type")

            if type_form.is_valid():
                type_form.save()
                messages.success(request, "Type created successfully.")
                return redirect("inventory_control_center")

            messages.error(request, "Please check the type form.")
            return redirect("inventory_control_center")

        # -------------------------
        # CREATE UNIT
        # -------------------------
        elif action == "create_unit":
            unit_form = UnitOptionForm(request.POST, prefix="unit")

            if unit_form.is_valid():
                unit_form.save()
                messages.success(request, "Unit created successfully.")
                return redirect("inventory_control_center")

            messages.error(request, "Please check the unit form.")
            return redirect("inventory_control_center")

        # -------------------------
        # RENAME / UPDATE TYPE
        # -------------------------
        elif action == "rename_type":
            type_id = request.POST.get("type_id")
            name = request.POST.get("name", "").strip()
            emoji = request.POST.get("emoji", "").strip()
            is_active = request.POST.get("is_active") == "on"

            item_type = get_object_or_404(ItemType, id=type_id)

            if not name:
                messages.error(request, "Type name is required.")
                return redirect("inventory_control_center")

            before_name = item_type.name

            item_type.name = name
            item_type.emoji = emoji or "📦"
            item_type.is_active = is_active
            item_type.save(update_fields=["name", "emoji", "is_active"])

            messages.success(request, f"Type updated: {before_name} → {item_type.name}")
            return redirect("inventory_control_center")

        # -------------------------
        # RENAME / UPDATE UNIT
        # -------------------------
        elif action == "rename_unit":
            unit_id = request.POST.get("unit_id")
            code = request.POST.get("code", "").strip().lower()
            name = request.POST.get("name", "").strip()
            emoji = request.POST.get("emoji", "").strip()
            is_active = request.POST.get("is_active") == "on"

            unit = get_object_or_404(UnitOption, id=unit_id)

            if not code or not name:
                messages.error(request, "Unit code and name are required.")
                return redirect("inventory_control_center")

            old_code = unit.code

            unit.code = code
            unit.name = name
            unit.emoji = emoji or "📏"
            unit.is_active = is_active
            unit.save(update_fields=["code", "name", "emoji", "is_active"])

            if old_code != code:
                Item.objects.filter(unit=old_code).update(unit=code)

            messages.success(request, "Unit updated successfully.")
            return redirect("inventory_control_center")

        # -------------------------
        # EDIT ITEM + RECORD HISTORY
        # -------------------------
        elif action == "edit_item":
            item_id = request.POST.get("item_id")

            item = get_object_or_404(
                Item.objects.select_related("item_type"),
                id=item_id,
            )

            before = snapshot_item(item)

            name = request.POST.get("name", "").strip()
            brand = request.POST.get("brand", "").strip()
            item_type_id = request.POST.get("item_type", "").strip()
            unit_code = request.POST.get("unit", "").strip()
            is_active = request.POST.get("is_active") == "on"

            if not name:
                messages.error(request, "Item name is required.")
                return redirect("inventory_control_center")

            item.name = name
            item.brand = brand
            item.is_active = is_active

            if item_type_id:
                item.item_type = ItemType.objects.filter(id=item_type_id).first()
            else:
                item.item_type = None

            if unit_code:
                item.unit = unit_code

            if request.POST.get("remove_image") == "1":
                delete_model_image(item, "image")

            if request.FILES.get("image"):
                delete_model_image(item, "image")
                item.image = request.FILES.get("image")

            item.save()

            after = snapshot_item(item)
            record_item_edit_history(item, request.user, before, after)

            messages.success(request, "Item updated successfully.")
            return redirect("inventory_control_center")

        else:
            messages.error(request, "Invalid action.")
            return redirect("inventory_control_center")

    item_types = ItemType.objects.all().order_by("name")
    units = UnitOption.objects.all().order_by("name")

    items = (
        Item.objects
        .select_related("item_type")
        .prefetch_related("edit_histories__edited_by")
        .order_by("name")
    )

    active_item_types = ItemType.objects.filter(is_active=True).order_by("name")
    active_units = UnitOption.objects.filter(is_active=True).order_by("name")

    return render(request, "inventory/inventory_control_center.html", {
        "type_form": type_form,
        "unit_form": unit_form,
        "item_types": item_types,
        "units": units,
        "items": items,
        "active_item_types": active_item_types,
        "active_units": active_units,
    })


# ==================================================
# ITEM TYPE
# ==================================================

@login_required
def item_type_create(request):
    if not can_create_inventory_type(request.user):
        messages.error(request, "You do not have permission to create an inventory type.")
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
@require_POST
def item_type_delete(request, pk):
    if not can_manage_inventory_settings(request.user):
        messages.error(request, "Only Owner/Admin can manage inventory settings.")
        return redirect("item_list")

    item_type = get_object_or_404(ItemType, pk=pk)
    used_count = Item.objects.filter(item_type=item_type).count()

    if used_count > 0:
        item_type.is_active = False
        item_type.save(update_fields=["is_active"])

        messages.warning(
            request,
            f"{item_type.name} is used by {used_count} item(s), so it was hidden instead of deleted.",
        )
        return redirect("inventory_control_center")

    type_name = item_type.name
    item_type.delete()

    messages.success(request, f"{type_name} deleted successfully.")
    return redirect("inventory_control_center")


# ==================================================
# UNIT OPTION
# ==================================================

@login_required
@require_POST
def unit_option_delete(request, pk):
    if not can_manage_inventory_settings(request.user):
        messages.error(request, "Only Owner/Admin can manage inventory settings.")
        return redirect("item_list")

    unit = get_object_or_404(UnitOption, pk=pk)
    used_count = Item.objects.filter(unit=unit.code).count()

    if used_count > 0:
        unit.is_active = False
        unit.save(update_fields=["is_active"])

        messages.warning(
            request,
            f"{unit.name} is used by {used_count} item(s), so it was hidden instead of deleted.",
        )
        return redirect("inventory_control_center")

    unit_name = unit.name
    unit.delete()

    messages.success(request, f"{unit_name} deleted successfully.")
    return redirect("inventory_control_center")



def _posted_variant_rows(request):
    """Return inline variant rows in the same order shown in the item form."""
    keys = request.POST.getlist("variant_key[]")
    variant_ids = request.POST.getlist("variant_id[]")
    labels = request.POST.getlist("variant_label[]")
    sizes = request.POST.getlist("variant_size[]")
    colors = request.POST.getlist("variant_color[]")
    skus = request.POST.getlist("variant_sku[]")
    cost_prices = request.POST.getlist("variant_cost_price[]")
    sale_prices = request.POST.getlist("variant_sale_price[]")
    active_values = request.POST.getlist("variant_active[]")

    rows = []

    for index, key in enumerate(keys):
        def value(values):
            return values[index].strip() if index < len(values) else ""

        row_key = str(key or "").strip()
        rows.append({
            "key": row_key,
            "variant_id": value(variant_ids),
            "label": value(labels),
            "size": value(sizes),
            "color": value(colors),
            "sku": value(skus),
            "cost_price": value(cost_prices),
            "sale_price": value(sale_prices),
            "is_active": value(active_values) != "0",
            "remove_image": request.POST.get(f"variant_remove_image_{row_key}") == "1",
            "image": request.FILES.get(f"variant_image_{row_key}"),
        })

    return rows


def _variant_rows_for_template(request, item=None, can_view_cost=False):
    """Build JSON-safe rows for create/edit and preserve submitted values on errors."""
    existing_variants = list(
        item.variants.all().order_by("sort_order", "id")
    ) if item and item.pk else []
    existing_map = {str(variant.id): variant for variant in existing_variants}

    if request.method == "POST":
        rows = _posted_variant_rows(request)
        for row in rows:
            existing = existing_map.get(str(row.get("variant_id") or ""))
            row["image_url"] = ""
            row["cost_status"] = "No Cost"

            if existing:
                row["cost_status"] = existing.cost_status
                if existing.image and not row.get("remove_image"):
                    try:
                        row["image_url"] = existing.image.url
                    except Exception:
                        row["image_url"] = ""

            row["cost_price"] = str(row.get("cost_price") or "")
            row["sale_price"] = str(row.get("sale_price") or "")
            row["is_active"] = bool(row.get("is_active", True))
            row.pop("image", None)
            row.pop("remove_image", None)

        return rows

    rows = []
    for index, variant in enumerate(existing_variants, start=1):
        image_url = ""
        if variant.image:
            try:
                image_url = variant.image.url
            except Exception:
                image_url = ""

        rows.append({
            "key": f"existing-{variant.id}",
            "variant_id": str(variant.id),
            "label": variant.label or "",
            "size": variant.size or "",
            "color": variant.color or "",
            "sku": variant.sku or "",
            "cost_price": str(variant.cost_price or "") if can_view_cost else "",
            "sale_price": str(variant.sale_price or ""),
            "is_active": bool(variant.is_active),
            "image_url": image_url,
            "cost_status": variant.cost_status,
        })

    return rows


def _validate_inline_variant_rows(item, rows):
    """Validate ownership and prevent duplicate SKUs before saving any row."""
    errors = []
    seen_skus = {}
    allowed_ids = set()

    if item and item.pk:
        allowed_ids = set(
            item.variants.values_list("id", flat=True)
        )

    for position, row in enumerate(rows, start=1):
        raw_id = str(row.get("variant_id") or "").strip()
        if raw_id:
            try:
                variant_id = int(raw_id)
            except (TypeError, ValueError):
                errors.append(f"Variant {position}: invalid variant record.")
                continue

            if not item or variant_id not in allowed_ids:
                errors.append(f"Variant {position}: this variant does not belong to the item.")

        sku = str(row.get("sku") or "").strip()
        if not sku:
            continue

        normalized = sku.casefold()
        if normalized in seen_skus:
            errors.append(
                f"SKU {sku} is repeated in variant {seen_skus[normalized]} and variant {position}."
            )
            continue
        seen_skus[normalized] = position

        duplicate_qs = ItemVariant.objects.filter(sku__iexact=sku)
        if raw_id.isdigit():
            duplicate_qs = duplicate_qs.exclude(pk=int(raw_id))

        if duplicate_qs.exists():
            errors.append(f"SKU {sku} is already used by another inventory variant.")

    return errors


def _save_inline_variants(request, item, can_edit_cost, user):
    """Create and update all item variants in one transaction without changing stock."""
    rows = _posted_variant_rows(request)
    existing_map = {
        str(variant.id): variant
        for variant in item.variants.select_for_update().all()
    }
    saved = []

    for position, row in enumerate(rows, start=1):
        existing = existing_map.get(str(row.get("variant_id") or ""))
        has_value = any([
            row.get("label"),
            row.get("size"),
            row.get("color"),
            row.get("sku"),
            row.get("cost_price"),
            row.get("sale_price"),
            row.get("image"),
        ])

        if not existing and not has_value:
            continue

        variant = existing or ItemVariant(item=item)
        before = snapshot_variant(variant) if existing else None

        variant.label = row.get("label", "")
        variant.size = row.get("size", "")
        variant.color = row.get("color", "")
        variant.sku = row.get("sku", "")
        variant.sort_order = position
        variant.is_active = bool(row.get("is_active", True))

        if can_edit_cost:
            entered_cost = str(row.get("cost_price") or "").strip()
            if entered_cost:
                variant.cost_price = money(
                    entered_cost,
                    variant.cost_price if existing else item.cost_price,
                )
            elif not existing:
                variant.cost_price = item.cost_price
        elif not existing:
            variant.cost_price = item.cost_price

        entered_sale = str(row.get("sale_price") or "").strip()
        if entered_sale:
            variant.sale_price = money(
                entered_sale,
                variant.sale_price if existing else item.sale_price,
            )
        elif not existing:
            variant.sale_price = item.sale_price

        if existing and row.get("remove_image"):
            delete_model_image(variant, "image")

        uploaded_image = row.get("image")
        if uploaded_image:
            if existing and variant.image:
                delete_model_image(variant, "image")
            variant.image = uploaded_image

        variant.save()

        if before is not None:
            record_variant_edit_history(
                variant,
                user,
                before,
                snapshot_variant(variant),
            )

        saved.append(variant)

    if not saved and not item.variants.exists():
        saved.append(
            ItemVariant.objects.create(
                item=item,
                label="Default",
                cost_price=item.cost_price,
                sale_price=item.sale_price,
                sort_order=1,
                is_active=True,
            )
        )

    return saved


def _create_inline_variants(request, item, can_price):
    """Backward-compatible wrapper used by item creation."""
    return _save_inline_variants(request, item, can_price, request.user)


# ==================================================
# ITEM CRUD
# ==================================================

@login_required
@transaction.atomic
def item_create(request):
    if not can_manage_inventory(request.user):
        messages.error(request, "You do not have permission.")
        return redirect("item_list")

    seed_default_units()
    can_price = can_edit_cost_price(request.user)
    can_view_cost = can_view_cost_price(request.user)

    form = ItemForm(
        request.POST or None,
        request.FILES or None,
        can_edit_cost_price=can_price,
        can_view_cost_price=can_view_cost,
        can_edit_sale_price=True,
    )

    variant_rows = _variant_rows_for_template(
        request,
        item=None,
        can_view_cost=can_view_cost,
    )
    variant_errors = []

    if request.method == "POST":
        posted_rows = _posted_variant_rows(request)
        variant_errors = _validate_inline_variant_rows(None, posted_rows)

        if form.is_valid() and not variant_errors:
            item = form.save(commit=False)

            if not can_price:
                item.cost_price = Decimal("0.00")

            if request.POST.get("remove_image") == "1":
                item.image = None

            item.save()
            created_variants = _save_inline_variants(
                request,
                item,
                can_price,
                request.user,
            )

            messages.success(
                request,
                f"Item created with {len(created_variants)} variant(s).",
            )
            return redirect("item_edit", pk=item.pk)

    return render(request, "inventory/item_form.html", {
        "form": form,
        "title": "Create Item",
        "is_create": True,
        "variant_rows": variant_rows,
        "variant_errors": variant_errors,
        "can_edit_cost_price": can_price,
        "can_view_cost_price": can_view_cost,
    })


@login_required
def item_detail(request, pk):
    current_branch = get_selected_branch(request)
    branches = Branch.objects.filter(is_active=True).order_by("name")

    variant_qs = ItemVariant.objects.order_by("sort_order", "id")

    item = get_object_or_404(
        Item.objects
        .select_related("item_type")
        .prefetch_related(Prefetch("variants", queryset=variant_qs)),
        pk=pk,
    )

    item.branch_stock_total = get_item_branch_qty(item, current_branch)

    for variant in item.variants.all():
        variant.branch_stock_qty = get_variant_branch_qty(
            variant,
            current_branch,
        )
        variant.branch_stock_rows = get_all_branch_stock_for_variant(variant)

    return render(request, "inventory/item_detail.html", {
        "item": item,
        "current_branch": current_branch,
        "branches": branches,
        "can_manage_inventory": can_manage_inventory(request.user),
        "can_view_cost_price": can_view_cost_price(request.user),
        "can_edit_cost_price": can_edit_cost_price(request.user),
    })


@login_required
@transaction.atomic
def item_edit(request, pk):
    if not can_manage_inventory(request.user):
        messages.error(request, "You do not have permission.")
        return redirect("item_list")

    seed_default_units()

    item = get_object_or_404(
        Item.objects.prefetch_related(
            Prefetch(
                "variants",
                queryset=ItemVariant.objects.order_by("sort_order", "id"),
            )
        ),
        pk=pk,
    )
    can_price = can_edit_cost_price(request.user)
    can_view_cost = can_view_cost_price(request.user)

    before = snapshot_item(item)
    old_cost_price = item.cost_price

    form = ItemForm(
        request.POST or None,
        request.FILES or None,
        instance=item,
        can_edit_cost_price=can_price,
        can_view_cost_price=can_view_cost,
        can_edit_sale_price=True,
    )

    variant_rows = _variant_rows_for_template(
        request,
        item=item,
        can_view_cost=can_view_cost,
    )
    variant_errors = []

    if request.method == "POST":
        posted_rows = _posted_variant_rows(request)
        variant_errors = _validate_inline_variant_rows(item, posted_rows)

        if form.is_valid() and not variant_errors:
            item = form.save(commit=False)

            if not can_price:
                item.cost_price = old_cost_price

            if request.POST.get("remove_image") == "1":
                delete_model_image(item, "image")

            item.save()

            after = snapshot_item(item)
            record_item_edit_history(item, request.user, before, after)

            saved_variants = _save_inline_variants(
                request,
                item,
                can_price,
                request.user,
            )

            messages.success(
                request,
                f"Item and {len(saved_variants)} variant(s) saved successfully.",
            )
            return redirect("item_edit", pk=item.pk)

    return render(request, "inventory/item_form.html", {
        "form": form,
        "title": "Edit Item",
        "is_create": False,
        "variant_rows": variant_rows,
        "variant_errors": variant_errors,
        "can_edit_cost_price": can_price,
        "can_view_cost_price": can_view_cost,
    })


@login_required
@require_POST
def item_delete(request, pk):
    if not can_manage_inventory(request.user):
        messages.error(request, "You do not have permission.")
        return redirect("item_list")

    item = get_object_or_404(Item, pk=pk)
    item_name = item.name

    try:
        # Permanently delete items that have no protected transaction history.
        item.delete()
        messages.success(
            request,
            f"{item_name} deleted successfully.",
        )

    except ProtectedError:
        # Keep past sales and stock records safe, but remove the item from
        # active inventory so staff no longer see or use it.
        item.is_active = False
        item.save(update_fields=["is_active"])

        ItemVariant.objects.filter(item=item).update(is_active=False)

        messages.warning(
            request,
            f"{item_name} has transaction history, so it was hidden instead of permanently deleted.",
        )

    except Exception:
        # Avoid a Server Error 500 for other database relationships.
        # Hide the item safely while preserving its related history.
        item.is_active = False
        item.save(update_fields=["is_active"])

        ItemVariant.objects.filter(item=item).update(is_active=False)

        messages.warning(
            request,
            f"{item_name} could not be permanently deleted, so it was hidden safely.",
        )

    return redirect("item_list")


# ==================================================
# VARIANT CRUD
# ==================================================

def clone_uploaded_image(uploaded_file):
    """
    Return a fresh file object for ImageField saving.
    Needed because the same Photo A / B / C upload can be used by many variants.
    """
    if not uploaded_file:
        return None

    try:
        uploaded_file.seek(0)
    except (AttributeError, OSError):
        pass

    return ContentFile(uploaded_file.read(), name=uploaded_file.name)


@login_required
@transaction.atomic
def item_variant_create(request, pk):
    if not can_manage_inventory(request.user):
        messages.error(request, "You do not have permission.")
        return redirect("item_list")

    item = get_object_or_404(Item, pk=pk)
    can_price = can_edit_cost_price(request.user)
    can_view_cost = can_view_cost_price(request.user)

    if request.method == "POST":
        rows = _posted_variant_rows(request)
        photo_sources = request.POST.getlist("variant_photo_source[]")
        group_keys = request.POST.getlist("variant_group_key[]")

        group_images = {}
        for raw_key in group_keys:
            key = str(raw_key or "").strip().lower()
            if not key:
                continue
            group_images[key] = request.FILES.get(f"variant_group_image_{key}")

        created = []

        last_variant = (
            ItemVariant.objects
            .filter(item=item)
            .order_by("-sort_order", "-id")
            .first()
        )
        last_order = last_variant.sort_order if last_variant else 0

        for index, row in enumerate(rows):
            photo_source = (
                photo_sources[index].strip().lower()
                if index < len(photo_sources)
                else "main"
            )

            if photo_source not in ["main", "custom"] and photo_source not in group_images:
                photo_source = "main"

            custom_image = row.get("image")

            has_value = any([
                row["sku"],
                row["size"],
                row["color"],
                row["label"],
                row["cost_price"],
                row["sale_price"],
                custom_image if photo_source == "custom" else None,
            ])

            if not has_value:
                continue

            if can_price:
                cost_price = money(row["cost_price"], item.cost_price)
                sale_price = money(row["sale_price"], item.sale_price)
            else:
                cost_price = item.cost_price
                sale_price = item.sale_price

            selected_image = None

            if photo_source in group_images:
                selected_image = clone_uploaded_image(group_images.get(photo_source))
            elif photo_source == "custom":
                selected_image = clone_uploaded_image(custom_image)

            # If selected_image is None, variant.display_image will fallback to item.image.
            variant = ItemVariant.objects.create(
                item=item,
                sku=row["sku"],
                image=selected_image,
                size=row["size"],
                color=row["color"],
                label=row["label"],
                cost_price=cost_price,
                sale_price=sale_price,
                sort_order=last_order + len(created) + 1,
                is_active=True,
            )

            created.append(variant)

        if not created:
            messages.error(request, "Please add at least one variant.")
            return redirect("item_variant_create", pk=item.pk)

        messages.success(
            request,
            f"{len(created)} variant(s) created successfully.",
        )
        return redirect("item_detail", pk=item.pk)

    return render(request, "inventory/item_variant_form.html", {
        "item": item,
        "title": "Create Variant",
        "is_bulk_create": True,
        "can_edit_cost_price": can_price,
        "can_view_cost_price": can_view_cost,
    })


@login_required
def item_variant_edit(request, pk, variant_id):
    if not can_manage_inventory(request.user):
        messages.error(request, "You do not have permission.")
        return redirect("item_list")

    item = get_object_or_404(Item, pk=pk)
    variant = get_object_or_404(ItemVariant, pk=variant_id, item=item)

    can_price = can_edit_cost_price(request.user)
    can_view_cost = can_view_cost_price(request.user)
    before = snapshot_variant(variant)

    old_cost_price = variant.cost_price
    old_sale_price = variant.sale_price

    form = ItemVariantForm(
        request.POST or None,
        request.FILES or None,
        instance=variant,
        can_edit_cost_price=can_price,
        can_view_cost_price=can_view_cost,
        can_edit_sale_price=True,
    )

    if request.method == "POST" and form.is_valid():
        variant = form.save(commit=False)

        if not can_price:
            variant.cost_price = old_cost_price
            variant.sale_price = old_sale_price

        if request.POST.get("remove_image") == "1":
            delete_model_image(variant, "image")

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
        "can_view_cost_price": can_view_cost,
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
@require_POST
def item_variant_reorder(request, pk):
    if not can_manage_inventory(request.user):
        return JsonResponse({
            "success": False,
            "message": "You do not have permission.",
        }, status=403)

    item = get_object_or_404(Item, pk=pk)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({
            "success": False,
            "message": "Invalid request data.",
        }, status=400)

    raw_ids = payload.get("variant_ids", [])

    try:
        variant_ids = [int(value) for value in raw_ids]
    except (TypeError, ValueError):
        return JsonResponse({
            "success": False,
            "message": "Invalid variant list.",
        }, status=400)

    valid_ids = set(
        ItemVariant.objects
        .filter(item=item, id__in=variant_ids)
        .values_list("id", flat=True)
    )

    if len(valid_ids) != len(variant_ids) or len(set(variant_ids)) != len(variant_ids):
        return JsonResponse({
            "success": False,
            "message": "One or more variants do not belong to this item.",
        }, status=400)

    with transaction.atomic():
        for position, variant_id in enumerate(variant_ids, start=1):
            ItemVariant.objects.filter(
                item=item,
                id=variant_id,
            ).update(sort_order=position)

    return JsonResponse({
        "success": True,
        "message": "Variant order saved.",
    })


# ==================================================
# STOCK MOVEMENT BY ITEM
# ==================================================

@login_required
def stock_movement(request, pk):
    if not can_manage_inventory(request.user):
        messages.error(request, "You do not have permission.")
        return redirect("item_list")

    item = get_object_or_404(
        Item.objects.prefetch_related("variants"),
        pk=pk,
    )
    can_cost = can_edit_cost_price(request.user)
    can_view_cost = can_view_cost_price(request.user)

    form = StockMovementForm(
        request.POST or None,
        item=item,
        user=request.user,
        can_edit_cost_price=can_cost,
        can_view_cost_price=can_view_cost,
    )

    if request.method == "POST" and form.is_valid():
        movement = form.save(commit=False)
        movement.item = item
        movement.created_by = request.user

        if not movement.branch:
            messages.error(request, "Please select shop/branch.")
            return redirect("stock_movement", pk=item.pk)

        if not movement.variant:
            messages.error(request, "Please select variant.")
            return redirect("stock_movement", pk=item.pk)

        current_qty = get_variant_branch_qty(
            movement.variant,
            movement.branch,
        )

        if movement.movement_type in ["out", "damage"] and movement.quantity > current_qty:
            messages.error(
                request,
                f"Not enough stock in {movement.branch.name}. Current stock: {current_qty}",
            )
            return redirect("stock_movement", pk=item.pk)

        movement.save()
        messages.success(request, f"Stock updated for {movement.branch.name}.")
        return redirect("item_detail", pk=item.pk)

    movements = (
        item.stock_movements
        .select_related("variant", "branch", "created_by")
        .order_by("-created_at")[:30]
    )

    return render(request, "inventory/stock_movement.html", {
        "item": item,
        "form": form,
        "movements": movements,
        "can_edit_cost_price": can_cost,
        "can_view_cost_price": can_view_cost,
    })


# ==================================================
# STOCK MOVEMENT BY VARIANT
# ==================================================

@login_required
def variant_stock_movement(request, variant_id):
    if not can_manage_inventory(request.user):
        messages.error(request, "You do not have permission.")
        return redirect("item_list")

    variant = get_object_or_404(
        ItemVariant.objects.select_related("item", "item__item_type"),
        pk=variant_id,
    )
    item = variant.item
    can_cost = can_edit_cost_price(request.user)
    can_view_cost = can_view_cost_price(request.user)

    selected_branch = get_selected_branch(request)

    if request.user.is_superuser:
        branches = Branch.objects.filter(is_active=True).order_by("name")
    else:
        user_branch = get_user_branch(request.user)
        branches = Branch.objects.filter(id=user_branch.id) if user_branch else Branch.objects.none()

    if not selected_branch:
        messages.error(request, "No branch assigned. Please ask admin to set your shop.")
        return redirect("item_detail", pk=item.id)

    current_stock = get_variant_branch_qty(variant, selected_branch)

    if request.method == "POST":
        movement_type = request.POST.get("movement_type", "in")
        quantity = int(request.POST.get("quantity") or 0)
        note = request.POST.get("note", "")

        posted_cost = request.POST.get("cost_price")

        if can_cost and str(posted_cost or "").strip():
            cost_price = money(posted_cost, variant.display_cost)
        else:
            cost_price = variant.display_cost

        if movement_type not in ["in", "out", "adjust", "damage"]:
            messages.error(request, "Invalid stock type.")
            return redirect("variant_stock_movement", variant_id=variant.id)

        if quantity <= 0:
            messages.error(request, "Quantity must be greater than 0.")
            return redirect("variant_stock_movement", variant_id=variant.id)

        if movement_type in ["out", "damage"] and quantity > current_stock:
            messages.error(
                request,
                f"Not enough stock in {selected_branch.name}. Current stock: {current_stock}",
            )
            return redirect("variant_stock_movement", variant_id=variant.id)

        StockMovement.objects.create(
            branch=selected_branch,
            item=item,
            variant=variant,
            movement_type=movement_type,
            quantity=quantity,
            cost_price=cost_price,
            note=note,
            created_by=request.user,
        )

        messages.success(request, f"Stock updated for {selected_branch.name}.")
        return redirect("item_detail", pk=item.id)

    movements = (
        variant.stock_movements
        .filter(branch=selected_branch)
        .select_related("branch", "created_by")
        .order_by("-created_at")[:30]
    )

    return render(request, "inventory/variant_stock_movement.html", {
        "item": item,
        "variant": variant,
        "branches": branches,
        "selected_branch": selected_branch,
        "current_stock": current_stock,
        "movements": movements,
        "can_edit_cost_price": can_cost,
        "can_view_cost_price": can_view_cost,
    })


# ==================================================
# VARIANT SEARCH API
# ==================================================

@login_required
@require_GET
def variant_search_api(request):
    if not can_manage_inventory(request.user):
        return JsonResponse({"results": []})

    q = request.GET.get("q", "").strip()
    selected_branch = get_selected_branch(request)

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

    variants = variants.order_by("item__name", "sort_order", "id")[:100]

    results = []
    user_can_view_cost = can_view_cost_price(request.user)

    for variant in variants:
        image_url = ""

        if variant.image:
            image_url = variant.image.url
        elif variant.item.image:
            image_url = variant.item.image.url

        branch_stock = get_variant_branch_qty(variant, selected_branch)

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
            "stock": branch_stock,
            "unit": variant.item.get_unit_display(),
            "cost_price": str(variant.display_cost) if user_can_view_cost else "",
            "cost_status": variant.cost_status,
            "can_view_cost": user_can_view_cost,
            "sale_price": str(variant.sale_price),
            "image": image_url,
        })

    return JsonResponse({"results": results})


# ==================================================
# BATCH STOCK IN
# ==================================================

@login_required
def stock_batch_in(request):
    if not can_manage_inventory(request.user):
        messages.error(request, "You do not have permission.")
        return redirect("item_list")

    can_cost = can_edit_cost_price(request.user)
    can_view_cost = can_view_cost_price(request.user)
    selected_branch = get_selected_branch(request)

    if request.user.is_superuser:
        branches = Branch.objects.filter(is_active=True).order_by("name")
    else:
        user_branch = get_user_branch(request.user)
        branches = (
            Branch.objects.filter(id=user_branch.id)
            if user_branch
            else Branch.objects.none()
        )

    if not selected_branch:
        messages.error(request, "No branch assigned. Please ask admin to set your shop.")
        return redirect("item_list")

    if request.method == "POST":
        branch_id = request.POST.get("branch")

        if request.user.is_superuser and branch_id:
            selected_branch = Branch.objects.filter(
                id=branch_id,
                is_active=True,
            ).first()

        if not selected_branch:
            messages.error(request, "Please select shop/branch.")
            return redirect("stock_batch_in")

        rows_json = request.POST.get("rows_json", "[]")

        try:
            rows = json.loads(rows_json)
        except json.JSONDecodeError:
            messages.error(request, "Invalid stock rows.")
            return redirect("stock_batch_in")

        saved_count = 0

        with transaction.atomic():
            for row in rows:
                variant_id = row.get("variant_id")
                qty_raw = row.get("quantity") or 0
                cost_raw = row.get("cost_price")
                note = str(row.get("note", "")).strip()

                try:
                    qty = int(qty_raw)
                except (TypeError, ValueError):
                    continue

                if not variant_id or qty <= 0:
                    continue

                variant = (
                    ItemVariant.objects
                    .select_related("item")
                    .filter(id=variant_id, is_active=True)
                    .first()
                )

                if not variant:
                    continue

                if can_cost and str(cost_raw or "").strip():
                    cost_price = money(cost_raw, variant.display_cost)
                else:
                    cost_price = variant.display_cost

                StockMovement.objects.create(
                    branch=selected_branch,
                    item=variant.item,
                    variant=variant,
                    movement_type="in",
                    quantity=qty,
                    cost_price=cost_price,
                    note=note or f"Batch stock in - {selected_branch.name}",
                    created_by=request.user,
                )
                saved_count += 1

        if saved_count:
            messages.success(
                request,
                f"{saved_count} stock row(s) saved for {selected_branch.name}.",
            )
            return redirect(
                f"{request.path}?branch={selected_branch.id}"
                if request.user.is_superuser
                else request.path
            )

        messages.error(request, "No valid stock rows to save.")
        return redirect("stock_batch_in")

    variant_qs = (
        ItemVariant.objects
        .filter(is_active=True)
        .order_by("sort_order", "id")
    )

    items = list(
        Item.objects
        .filter(is_active=True)
        .select_related("item_type")
        .prefetch_related(Prefetch("variants", queryset=variant_qs))
        .order_by("name", "id")
    )

    for item in items:
        item.branch_stock_total = 0

        for variant in item.variants.all():
            variant.branch_stock_qty = get_variant_branch_qty(
                variant,
                selected_branch,
            )
            item.branch_stock_total += variant.branch_stock_qty

    return render(request, "inventory/stock_batch_in.html", {
        "items": items,
        "item_types": ItemType.objects.filter(is_active=True).order_by("name"),
        "branches": branches,
        "selected_branch": selected_branch,
        "can_edit_cost_price": can_cost,
        "can_view_cost_price": can_view_cost,
    })


# ==================================================
# BARCODE LABEL
# ==================================================

@login_required
def variant_barcode_label(request, variant_id):
    if not can_manage_inventory(request.user):
        messages.error(request, "You do not have permission.")
        return redirect("item_list")

    # Read only: this view never saves or changes the variant/database.
    variant = get_object_or_404(
        ItemVariant.objects.select_related("item", "item__item_type"),
        pk=variant_id,
    )

    original_sku = str(variant.sku or "").strip()

    # python-barcode Code 128 supports ASCII. Some existing SKUs may contain
    # Khmer, emoji, or other unsupported Unicode characters, which caused
    # only those variants to return Server Error 500.
    safe_sku = "".join(
        character
        for character in original_sku
        if character.isascii()
        and (character.isalnum() or character in "-._/")
    )

    # Runtime-only fallback. Nothing is written to the database.
    if not safe_sku:
        safe_sku = f"VAR-{variant.id}"

    try:
        barcode_class = barcode.get_barcode_class("code128")
        barcode_obj = barcode_class(safe_sku, writer=ImageWriter())

        buffer = BytesIO()
        barcode_obj.write(buffer, options={
            "write_text": False,
            "module_height": 10,
            "module_width": 0.35,
            "font_size": 8,
            "text_distance": 2,
            "quiet_zone": 2,
        })
    except Exception:
        # Final safe fallback for any unexpected invalid barcode value.
        safe_sku = f"VAR-{variant.id}"
        barcode_class = barcode.get_barcode_class("code128")
        barcode_obj = barcode_class(safe_sku, writer=ImageWriter())

        buffer = BytesIO()
        barcode_obj.write(buffer, options={
            "write_text": False,
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
        "barcode_value": safe_sku,
        "original_sku": original_sku,
    })


# ==================================================
# BRANCH / SHOP
# ==================================================

@login_required
def branch_list(request):
    """
    Shop management.

    Permission rule:
    - Only superuser/admin can create or edit shops.
    - Normal staff/cashier cannot manage branch/shop records.
    """
    if not request.user.is_superuser:
        messages.error(request, "Only admin can manage shops.")
        return redirect("item_list")

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
    """
    Delete shop.

    Permission rule:
    - Only superuser/admin can delete shops.
    """
    if not request.user.is_superuser:
        messages.error(request, "Only admin can delete shops.")
        return redirect("item_list")

    branch = get_object_or_404(Branch, pk=pk)

    branch.delete()

    messages.success(request, "Shop deleted successfully.")
    return redirect("branch_list")


@login_required
@require_POST
def branch_toggle(request, pk):
    """
    Toggle shop active/inactive.

    Permission rule:
    - Only superuser/admin can activate or deactivate shops.
    """
    if not request.user.is_superuser:
        return JsonResponse({
            "success": False,
            "message": "Only admin can update shop status.",
        }, status=403)

    branch = get_object_or_404(Branch, pk=pk)
    branch.is_active = request.POST.get("status") == "true"
    branch.save(update_fields=["is_active"])

    return JsonResponse({
        "success": True,
        "is_active": branch.is_active,
    })