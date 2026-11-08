"""Simple in-app administration for branch shifts and past/future holidays."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import transaction
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time
from inventory.models import Branch
from users.models import StaffProfile
from .models import StaffBranchSchedule, StaffHoliday


def _is_admin(user):
    return user.is_active and (user.is_superuser or user.has_perm('auth.change_user'))


@login_required
@user_passes_test(_is_admin)
def schedules_and_holidays(request):
    if request.method == 'POST':
        kind = request.POST.get('kind')
        if kind == 'schedule':
            staff = get_object_or_404(StaffProfile, pk=request.POST.get('staff'))
            branch = get_object_or_404(Branch, pk=request.POST.get('branch'))
            start = parse_time(request.POST.get('start_time', ''))
            end = parse_time(request.POST.get('end_time', ''))
            from_date = parse_date(request.POST.get('valid_from', ''))
            until_str = request.POST.get('valid_until', '')
            until = parse_date(until_str) if until_str else None
            try:
                grace = int(request.POST.get('late_grace_minutes', '10'))
            except (ValueError, TypeError):
                grace = -1
            if not (start and end and from_date and (not until_str or until) and (not until or until >= from_date) and 0 <= grace <= 240):
                messages.error(request, 'Check the shift times, dates and late grace period.')
            else:
                # One schedule row per staff, branch and effective start; edit by re-saving.
                StaffBranchSchedule.objects.update_or_create(
                    staff=staff, branch=branch, valid_from=from_date,
                    defaults=dict(start_time=start, end_time=end, valid_until=until,
                                  late_grace_minutes=grace, active=True,
                                  updated_by=request.user),
                )
                messages.success(request, 'Branch work schedule saved. Staff can use this branch QR.')
        elif kind == 'holiday':
            title = request.POST.get('title', '').strip()[:150]
            start = parse_date(request.POST.get('date_from', ''))
            end = parse_date(request.POST.get('date_to', ''))
            scope = request.POST.get('scope', 'all')
            branch = get_object_or_404(Branch, pk=request.POST.get('branch')) if scope == 'branch' else None
            staff = get_object_or_404(StaffProfile, pk=request.POST.get('staff')) if scope == 'staff' else None
            if not title or not start or not end or start > end or scope not in ('all', 'branch', 'staff'):
                messages.error(request, 'Provide a name, valid dates and holiday scope.')
            else:
                StaffHoliday.objects.create(title=title, date_from=start, date_to=end,
                    scope=scope, branch=branch, staff=staff,
                    paid=request.POST.get('paid') == 'on', created_by=request.user)
                messages.success(request, 'Holiday saved, including for past dates. Attendance reports will recalculate.')
        else:
            messages.error(request, 'Unknown form submission.')
        return redirect('staff_schedules_holidays')

    schedules = StaffBranchSchedule.objects.select_related('staff__user','branch').order_by('staff__user__username','branch__name','-valid_from')[:200]
    holidays = StaffHoliday.objects.select_related('branch','staff__user').order_by('-date_from','-pk')[:200]
    return render(request, 'staffs/schedules_and_holidays.html', dict(
        staffs=StaffProfile.objects.select_related('user','branch').order_by('user__username'),
        branches=Branch.objects.all().order_by('name'), schedules=schedules, holidays=holidays,
        today=timezone.localdate()))
