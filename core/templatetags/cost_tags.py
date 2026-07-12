from decimal import Decimal, InvalidOperation

from django import template

from core.cost_access import can_view_cost, cost_status


register = template.Library()


def _money(value):
    try:
        return f"${Decimal(str(value or 0)):,.2f}"
    except (InvalidOperation, TypeError, ValueError):
        return "$0.00"


@register.simple_tag(takes_context=True)
def cost_display(context, value):
    """Owner sees amount. Staff sees only No Cost / Already Added."""
    request = context.get("request")
    user = getattr(request, "user", None)

    if can_view_cost(user):
        return _money(value)

    return cost_status(value)


@register.filter
def cost_state(value):
    return cost_status(value)
