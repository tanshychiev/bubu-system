#!/usr/bin/env python3
"""Apply guarded additive BUBU feature update. Run from package directory on Ubuntu."""
import ast
import shutil
import sys
from pathlib import Path
from datetime import datetime

SRC = Path(__file__).resolve().parent
ROOT = Path('/var/www/bubu')
FILES = {'models': ROOT/'staffs/models.py', 'views': ROOT/'staffs/views.py', 'urls':ROOT/'staffs/urls.py',
         'admin':ROOT/'staffs/admin.py', 'report':ROOT/'templates/staffs/staff_attendance_report.html',
         'settings':ROOT/'templates/staffs/staff_setting_list.html'}


def require_one(text, old, label):
    n = text.count(old)
    if n != 1:
        raise ValueError(f'{label}: expected exactly one matching block, found {n}; no files changed')
    return text


def repl(text, old, new, label):
    require_one(text, old, label)
    return text.replace(old, new, 1)

try:
    originals={key:path.read_text() for key,path in FILES.items()}
    out=dict(originals)
    if 'class StaffBranchSchedule(models.Model):' in out['models']:
        raise ValueError('StaffBranchSchedule model already installed. No changes made.')
    out['models'] += '\n' + (SRC/'models_addition.txt').read_text()
    out['admin'] += '\n' + (SRC/'admin_addition.txt').read_text()
    out['urls']=repl(out['urls'], 'from . import views, work_views',
        'from . import views, work_views, schedule_admin_views', 'URL imports')
    out['urls']=repl(out['urls'], 'urlpatterns = [',
        'urlpatterns = [\n    path("schedules/", schedule_admin_views.schedules_and_holidays, name="staff_schedules_holidays"),', 'URL route')
    out['settings']=repl(out['settings'], '{% block content %}',
        '{% block content %}\n<div style="padding:10px 0"><a href="{% url \'staff_schedules_holidays\' %}" style="display:inline-block;padding:12px 17px;border-radius:12px;background:#7259d9;color:white;font-weight:700">Branch Schedules &amp; Holidays</a></div>',
        'staff settings navigation')
    v=out['views']
    v=repl(v, 'from staffs.telegram import send_staff_telegram_message, send_staff_telegram_async',
       'from staffs.telegram import send_staff_telegram_message, send_staff_telegram_async\n'
       'from staffs.branch_scheduling import schedule_for, branch_allowed, shift_for, effective_absence_count, effective_attendance_status', 'views imports')
    v=repl(v, 'if not staff or staff.branch_id != qr.branch_id:',
            'if not staff or not branch_allowed(staff, qr.branch, timezone.localdate()):', 'GET branch authorization')
    v=repl(v, 'if not staff or staff.branch_id != qr.branch_id or not staff.user.is_active:',
            'if not staff or not branch_allowed(staff, qr.branch, timezone.localdate()) or not staff.user.is_active:', 'POST branch authorization')
    # In GET use a branch-specific shift ONLY for lateness; don't assign synthetic objects to FK.
    v=repl(v, 'arrival_status = _check_arrival_status(timezone.localdate(), timezone.localtime(), shift)[0]',
       'arrival_status = _check_arrival_status(timezone.localdate(), timezone.localtime(), shift_for(staff, qr.branch, timezone.localdate(), shift))[0]', 'GET shift')
    # Allow existing staff to scan with branch schedule even if salary not configured.
    v=repl(v, 'if not setting:\n        messages.error(request, "Payroll setting not found. Please contact admin.")',
       'if not setting and not schedule_for(staff, qr.branch, timezone.localdate()):\n        messages.error(request, "Payroll setting not found. Please contact admin.")', 'payroll attendance gate')
    # Use date-specific schedule for lateness, not persisted FK shift
    find='status, minutes_value, status_text, status_icon = _check_arrival_status(\n        today=today, now=now, shift=shift,\n    )'
    replace='status, minutes_value, status_text, status_icon = _check_arrival_status(\n        today=today, now=now, shift=shift_for(staff, qr.branch, today, shift),\n    )'
    v=repl(v,find,replace,'branch lateness calculation')
    # In the report, exclude retroactive holidays from historical absent count.
    v=repl(v, 'absent_days = attendances.filter(status="absent").count()',
       'absent_days = effective_absence_count(attendances)', 'attendance report absence count')
    v=repl(v, 'absent_count = attendances.filter(status="absent").count()',
       'absent_count = effective_absence_count(attendances)', 'salary preview absence count')
    v=repl(v, 'attendance_rows.append({\n            "attendance": row,',
       'row.effective_status_label = ("Worked on Holiday" if effective_attendance_status(row) == "worked_holiday" else "Holiday" if effective_attendance_status(row) == "holiday" else row.get_status_display())\n        attendance_rows.append({\n            "attendance": row,', 'attendance report row')
    out['views']=v
    out['report']=repl(out['report'], '{{ row.get_status_display }}',
        '{{ row.effective_status_label }}', 'report status text')
    # Syntax check all Python prior to any filesystem mutation.
    for k in ('models','views','urls','admin'):
        ast.parse(out[k],filename=str(FILES[k]))
    for src in (SRC/'staffs/branch_scheduling.py', SRC/'staffs/schedule_admin_views.py', SRC/'staffs/migrations/0006_staff_branch_schedules_holidays.py'):
        ast.parse(src.read_text(), filename=str(src))
    # Protect against overwrite of previously installed migration.
    additions={
        ROOT/'staffs/branch_scheduling.py':SRC/'staffs/branch_scheduling.py',
        ROOT/'staffs/schedule_admin_views.py':SRC/'staffs/schedule_admin_views.py',
        ROOT/'staffs/migrations/0006_staff_branch_schedules_holidays.py':SRC/'staffs/migrations/0006_staff_branch_schedules_holidays.py',
        ROOT/'templates/staffs/schedules_and_holidays.html':SRC/'templates/staffs/schedules_and_holidays.html',
    }
    for dest in additions:
        if dest.exists():
            raise ValueError(f'File already exists: {dest}; no changes made')
    timestamp=datetime.now().strftime('%Y%m%d-%H%M%S')
    backup=Path('/root')/f'bubu-before-multibranch-{timestamp}'
    backup.mkdir(parents=True,exist_ok=False)
    for key,p in FILES.items():
        target=backup/p.relative_to(ROOT)
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(p,target)
    for key,p in FILES.items():
        p.write_text(out[key])
    for dest,src in additions.items():
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src,dest)
    print('Update files installed. Backup:',backup)
    print('NEXT: run python manage.py check and python manage.py migrate staffs')
except Exception as exc:
    print('INSTALL STOPPED:',exc)
    sys.exit(1)
