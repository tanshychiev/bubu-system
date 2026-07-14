from __future__ import annotations

from datetime import datetime
from pathlib import Path
from shutil import copy2

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import no_style
from django.db import connections, transaction
from django.db.models.deletion import ProtectedError
from django.db.utils import IntegrityError


BUSINESS_APP_LABELS = {
    "customers",
    "delivery",
    "inventory",
    "pets",
    "pos",
    "purchases",
    "staffs",
}

# These records are configuration/identity records and must survive the reset.
PRESERVED_MODELS = {
    "inventory.branch",             # Shop/branch + payment QR fields
    "pos.possetting",               # Exchange rate
    "pos.branchcashfloat",          # Starting cash float per branch
    "staffs.branchattendanceqr",    # Attendance QR token/configuration
    "staffs.staffpayrollsetting",   # Staff salary/commission configuration
    "staffs.staffshift",            # Staff work schedule configuration
    "staffs.staffworkday",          # Staff weekly work-day configuration
}


class Command(BaseCommand):
    help = (
        "Delete BUBU business/test data while keeping users, staff profiles, "
        "roles, permissions, branches, payment QR, attendance QR and selected settings."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            default="",
            help='Required confirmation phrase: RESET-BUBU',
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without changing the database.",
        )
        parser.add_argument(
            "--database",
            default="default",
            help="Database alias to reset. Default: default",
        )

    def handle(self, *args, **options):
        alias = options["database"]
        dry_run = bool(options["dry_run"])
        confirm = str(options["confirm"] or "").strip()

        if alias not in connections:
            raise CommandError(f"Unknown database alias: {alias}")

        connection = connections[alias]
        target_models = self._target_models()

        if not target_models:
            raise CommandError("No BUBU business models were found.")

        self.stdout.write(self.style.WARNING(
            "This reset keeps:"
        ))
        self.stdout.write(
            "  • Owner/Admin and Staff user accounts\n"
            "  • Staff profiles, groups, roles and permissions\n"
            "  • Shop/branch records\n"
            "  • Branch payment QR image/label\n"
            "  • Branch attendance QR\n"
            "  • POS exchange rate and branch cash-float settings\n"
            "  • Staff payroll/schedule configuration"
        )

        self.stdout.write(self.style.WARNING(
            "\nThis reset deletes business records from:"
        ))
        self.stdout.write(
            "  customers, delivery, inventory, pets, POS, purchases and "
            "staff transaction/payroll history"
        )

        rows = []
        total_rows = 0

        for model in target_models:
            count = model._default_manager.using(alias).count()
            rows.append((model._meta.label, count))
            total_rows += count

        self.stdout.write("\nModels selected for deletion:")
        for label, count in rows:
            self.stdout.write(f"  {label}: {count}")

        self.stdout.write(self.style.WARNING(
            f"\nTotal model rows selected: {total_rows}"
        ))

        if dry_run:
            self.stdout.write(self.style.SUCCESS(
                "\nDRY RUN ONLY. No records were deleted."
            ))
            return

        if confirm != "RESET-BUBU":
            raise CommandError(
                'Reset cancelled. Run again with: --confirm RESET-BUBU'
            )

        backup_path = self._make_sqlite_backup(alias)
        self.stdout.write(self.style.SUCCESS(
            f"\nDatabase backup created: {backup_path}"
        ))

        deleted_summary = {}
        pending = list(target_models)

        # QuerySet.delete() handles Django cascades and signals. Some models may
        # initially be blocked by PROTECT relationships, so retry blocked models
        # after their dependent models have been deleted.
        with transaction.atomic(using=alias):
            max_rounds = max(len(pending) * 3, 3)

            for _round in range(max_rounds):
                if not pending:
                    break

                next_pending = []
                made_progress = False

                for model in pending:
                    queryset = model._default_manager.using(alias).all()

                    if not queryset.exists():
                        deleted_summary.setdefault(model._meta.label, 0)
                        made_progress = True
                        continue

                    try:
                        deleted_count, details = queryset.delete()
                        deleted_summary[model._meta.label] = (
                            deleted_summary.get(model._meta.label, 0)
                            + deleted_count
                        )
                        made_progress = True

                        # Include cascaded model counts in the report.
                        for label, count in details.items():
                            deleted_summary[label] = (
                                deleted_summary.get(label, 0) + count
                            )

                    except (ProtectedError, IntegrityError):
                        next_pending.append(model)

                if not next_pending:
                    pending = []
                    break

                if not made_progress or len(next_pending) == len(pending):
                    pending = next_pending
                    break

                pending = next_pending

            remaining = []

            for model in pending:
                count = model._default_manager.using(alias).count()
                if count:
                    remaining.append(f"{model._meta.label} ({count})")

            if remaining:
                raise CommandError(
                    "Reset rolled back because these models could not be safely "
                    "deleted: " + ", ".join(remaining)
                )

            # Reset IDs only for emptied business models. Preserved users,
            # branches and staff configuration keep their existing IDs.
            sql_list = connection.ops.sequence_reset_sql(no_style(), target_models)
            with connection.cursor() as cursor:
                for sql in sql_list:
                    cursor.execute(sql)

        self.stdout.write(self.style.SUCCESS(
            "\nBUBU business data reset completed successfully."
        ))
        self.stdout.write("Deleted records:")
        for label in sorted(deleted_summary):
            self.stdout.write(f"  {label}: {deleted_summary[label]}")

        self.stdout.write(self.style.WARNING(
            "\nUploaded media files were not deleted. Branch QR files remain safe."
        ))

    def _target_models(self):
        target_models = []

        for model in apps.get_models():
            app_label = model._meta.app_label
            label_lower = model._meta.label_lower

            if app_label not in BUSINESS_APP_LABELS:
                continue

            if label_lower in PRESERVED_MODELS:
                continue

            target_models.append(model)

        # Try highly dependent models first. The retry loop handles anything
        # whose dependency order cannot be inferred from this simple score.
        def dependency_score(model):
            score = 0
            for field in model._meta.get_fields():
                if (
                    getattr(field, "many_to_one", False)
                    or getattr(field, "one_to_one", False)
                ) and getattr(field, "remote_field", None):
                    related = field.remote_field.model
                    if related and related._meta.app_label in BUSINESS_APP_LABELS:
                        score += 1
            return score

        return sorted(
            target_models,
            key=lambda model: (dependency_score(model), model._meta.label_lower),
            reverse=True,
        )

    def _make_sqlite_backup(self, alias):
        db_config = settings.DATABASES[alias]
        engine = str(db_config.get("ENGINE", ""))

        if "sqlite3" not in engine:
            raise CommandError(
                "Automatic backup is only supported for SQLite. "
                "No data was deleted. Make a database backup first."
            )

        db_name = db_config.get("NAME")
        if not db_name or str(db_name) == ":memory:":
            raise CommandError(
                "Cannot back up an in-memory SQLite database. No data was deleted."
            )

        db_path = Path(db_name).resolve()

        if not db_path.exists():
            raise CommandError(
                f"SQLite database was not found: {db_path}. No data was deleted."
            )

        backup_dir = Path(settings.BASE_DIR) / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"bubu_before_reset_{timestamp}.sqlite3"

        # Close active connections so the copied SQLite file is consistent.
        connections.close_all()
        copy2(db_path, backup_path)

        return backup_path
