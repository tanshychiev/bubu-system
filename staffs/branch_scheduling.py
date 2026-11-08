"""Historical staff branch schedules and holiday status, never mutate recorded scans."""
from datetime import timedelta
from types import SimpleNamespace
from django.db.models import Q
from django.utils import timezone

from .models import StaffBranchSchedule, StaffHoliday


def schedule_for(staff, branch, day=None):
    day = day or timezone.localdate()
    return (StaffBranchSchedule.objects.filter(staff=staff, branch=branch, active=True, valid_from__lte=day)
            .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=day))
            .order_by('-valid_from', '-pk').first())


def branch_allowed(staff, branch, day=None):
    if not staff:
        return False
    day = day or timezone.localdate()
    # Explicit schedules override the legacy single primary-branch membership
    # for a branch/date, but retain compatibility with existing staff.
    return bool(schedule_for(staff, branch, day) or staff.branch_id == branch.pk)


def shift_for(staff, branch, day, legacy_shift):
    assignment = schedule_for(staff, branch, day)
    if not assignment:
        return legacy_shift
    return SimpleNamespace(start_time=assignment.start_time, end_time=assignment.end_time,
                           late_after_minutes=assignment.late_grace_minutes, pk=None)


def holiday_for(staff, branch, day):
    """Return holiday as of *historical* date; None if holiday doesn't apply."""
    if branch is None:
        branch = getattr(staff, 'branch', None)
    branch_id = getattr(branch, 'pk', None)
    scope = Q(scope='all') | Q(scope='staff', staff=staff)
    if branch_id:
        scope |= Q(scope='branch', branch_id=branch_id)
    return (StaffHoliday.objects.filter(active=True, date_from__lte=day, date_to__gte=day)
            .filter(scope).order_by('-pk').first())


def effective_attendance_status(attendance):
    h = holiday_for(attendance.staff, attendance.branch, attendance.date)
    if not h:
        return attendance.status
    if attendance.check_in_time or attendance.check_out_time:
        return 'worked_holiday'
    return 'holiday' if attendance.status == 'absent' else attendance.status


def effective_absence_count(qs):
    """Exclude retroactively declared holiday absences without changing historical records."""
    return sum(1 for record in qs.filter(status='absent').select_related('staff', 'branch')
               if effective_attendance_status(record) == 'absent')
