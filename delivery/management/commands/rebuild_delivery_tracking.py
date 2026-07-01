from django.core.management.base import BaseCommand

from delivery.models import Delivery


class Command(BaseCommand):
    help = "Recalculate COD status and lack amount for all existing deliveries."

    def handle(self, *args, **options):
        updated = 0
        for delivery in Delivery.objects.all().iterator():
            delivery.save(update_fields=["cod_status", "lack_amount", "updated_at"])
            updated += 1

        self.stdout.write(self.style.SUCCESS(f"Updated {updated} delivery record(s)."))
