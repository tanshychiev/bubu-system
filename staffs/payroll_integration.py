# Add these imports near the top of staffs/views.py
from .models import GroomingWorkRecord, StaffWorkCommissionRule, PayrollAdjustment


def _work_commission_for_period(staff, period_start, period_end):
    """Calculate commission from CONFIRMED work only. Staff never sees POS expected totals."""
    quantities = {
        row["work_type_id"]: Decimal(row["total"] or 0)
        for row in GroomingWorkRecord.objects.filter(
            staff=staff,
            status="confirmed",
            work_date__gte=period_start,
            work_date__lte=period_end,
            payroll_record__isnull=True,
        ).values("work_type_id").annotate(total=Sum("quantity"))
    }

    total = Decimal("0.00")
    breakdown = []
    for work_type_id, quantity in quantities.items():
        rule = (
            StaffWorkCommissionRule.objects
            .filter(
                staff=staff,
                work_type_id=work_type_id,
                is_active=True,
                effective_from__lte=period_end,
            )
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=period_start))
            .select_related("work_type")
            .order_by("-effective_from", "-id")
            .first()
        )
        amount = rule.calculate(quantity) if rule else Decimal("0.00")
        total += amount
        breakdown.append({
            "work_type": rule.work_type.name if rule else f"Work #{work_type_id}",
            "quantity": quantity,
            "amount": amount,
            "rule": rule.get_calculation_type_display() if rule else "No rule",
        })
    return total, breakdown


def _adjustments_for_period(staff, period_start, period_end):
    rows = PayrollAdjustment.objects.filter(
        staff=staff,
        record_date__gte=period_start,
        record_date__lte=period_end,
        payroll_record__isnull=True,
    )
    bonus = rows.filter(adjustment_type="bonus").aggregate(v=Sum("amount"))["v"] or Decimal("0.00")
    deductions = rows.filter(adjustment_type__in=["deduction", "advance"]).aggregate(v=Sum("amount"))["v"] or Decimal("0.00")
    return rows, bonus, deductions


# Inside staff_salary_open(), BEFORE payroll.save(), add:
#
# work_commission, work_breakdown = _work_commission_for_period(
#     setting.staff, preview["period_start"], preview["period_end"]
# )
# adjustment_rows, manual_bonus, manual_deduction = _adjustments_for_period(
#     setting.staff, preview["period_start"], preview["period_end"]
# )
# payroll.grooming_commission = work_commission
# payroll.total_commission = Decimal(payroll.pet_sale_commission or 0) + work_commission
# payroll.bonus = manual_bonus
# payroll.other_deduction = manual_deduction
#
# AFTER payroll.save(), add:
# GroomingWorkRecord.objects.filter(
#     staff=setting.staff,
#     status="confirmed",
#     payroll_record__isnull=True,
#     work_date__gte=preview["period_start"],
#     work_date__lte=preview["period_end"],
# ).update(status="locked", payroll_record=payroll)
# adjustment_rows.update(payroll_record=payroll)
#
# Remove the old GroomingCommission.objects.filter(...).update(...) block.
#
# In payroll_record_detail(), add:
# work_records = payroll.grooming_work_records.select_related("work_type").all()
# adjustments = payroll.adjustments.all()
# and include both in render context.
