from decimal import Decimal, InvalidOperation


OWNER_ROLE_NAMES = {
    "Owner/Admin",
    "BUBU Owner",
    "Owner",
    "Admin",
}

STAFF_ROLE_NAMES = {
    "Staff",
    "BUBU Staff",
}


def _has_group(user, names):
    if not user or not getattr(user, "is_authenticated", False):
        return False

    return user.groups.filter(name__in=names).exists()


def is_owner(user):
    """Owner/Admin can see real cost, profit, payroll and settings."""
    if not user or not getattr(user, "is_authenticated", False):
        return False

    return bool(user.is_superuser or _has_group(user, OWNER_ROLE_NAMES))


def is_staff_role(user):
    """Normal BUBU staff. Staff can enter cost but cannot read it."""
    if not user or not getattr(user, "is_authenticated", False):
        return False

    if is_owner(user):
        return False

    return bool(_has_group(user, STAFF_ROLE_NAMES) or user.is_staff)


def can_view_cost(user):
    return is_owner(user)


def can_edit_cost(user):
    return is_owner(user) or is_staff_role(user)


def has_cost(value):
    try:
        return Decimal(str(value or "0")) > 0
    except (InvalidOperation, TypeError, ValueError):
        return False


def cost_status(value):
    return "Already Added" if has_cost(value) else "No Cost"
