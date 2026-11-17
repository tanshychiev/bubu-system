from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("staffs", "0006_staff_branch_schedules_holidays")]
    operations = [migrations.AddField(model_name="staffattendance", name="checkout_reason", field=models.TextField(blank=True))]
