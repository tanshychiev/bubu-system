from django.db import migrations, models


def deduplicate_branch_qrs(apps, schema_editor):
    QR = apps.get_model("staffs", "BranchAttendanceQR")
    branch_ids = QR.objects.order_by().values_list("branch_id", flat=True).distinct()
    for branch_id in branch_ids:
        codes = list(QR.objects.filter(branch_id=branch_id).order_by("-is_active", "created_at", "pk"))
        # Preserve the oldest active QR token so printed QR posters keep working.
        for duplicate in codes[1:]:
            duplicate.delete()


class Migration(migrations.Migration):
    dependencies = [("staffs", "0004_groomingworktype_groominghelperwork_and_more")]
    operations = [
        migrations.RunPython(deduplicate_branch_qrs, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="branchattendanceqr",
            constraint=models.UniqueConstraint(fields=("branch",), name="one_attendance_qr_per_branch"),
        ),
    ]
