from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ('staffs', '0005_one_attendance_qr_per_branch'),
        ('inventory', '0008_branch_branchstock'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='StaffBranchSchedule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('start_time', models.TimeField()),
                ('end_time', models.TimeField()),
                ('late_grace_minutes', models.PositiveIntegerField(default=10)),
                ('valid_from', models.DateField(default=django.utils.timezone.localdate)),
                ('valid_until', models.DateField(blank=True, null=True)),
                ('active', models.BooleanField(default=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='staff_schedules', to='inventory.branch')),
                ('staff', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='branch_schedules', to='users.staffprofile')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['staff__user__username', 'branch__name', '-valid_from']},
        ),
        migrations.CreateModel(
            name='StaffHoliday',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=150)),
                ('date_from', models.DateField()),
                ('date_to', models.DateField()),
                ('scope', models.CharField(choices=[('all','All branches'),('branch','One branch'),('staff','One staff')], default='all', max_length=10)),
                ('paid', models.BooleanField(default=True)),
                ('active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('branch', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='staff_holidays', to='inventory.branch')),
                ('staff', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='holidays', to='users.staffprofile')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-date_from', '-id']},
        ),
        migrations.AddConstraint(model_name='staffbranchschedule', constraint=models.UniqueConstraint(fields=('staff','branch','valid_from'), name='bubu_schedule_staff_branch_start')),
    ]
