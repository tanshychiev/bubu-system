from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [("users", "0002_alter_staffprofile_options"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [migrations.CreateModel(name="LoginQRToken", fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("token_hash", models.CharField(db_index=True, max_length=64, unique=True)),
        ("created_at", models.DateTimeField(auto_now_add=True)),
        ("expires_at", models.DateTimeField()),
        ("used_at", models.DateTimeField(blank=True, null=True)),
        ("revoked_at", models.DateTimeField(blank=True, null=True)),
        ("created_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="issued_login_qrs", to=settings.AUTH_USER_MODEL)),
        ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="login_qr_tokens", to=settings.AUTH_USER_MODEL)),
    ], options={"ordering": ["-created_at"]})]
