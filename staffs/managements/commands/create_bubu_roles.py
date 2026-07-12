from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

from inventory.models import Item


CUSTOM_INVENTORY_PERMISSIONS = [
    ("can_view_cost_price", "Can view cost price and profit"),
    ("can_edit_cost_price", "Can enter/edit cost price"),
]


ROLE_PERMISSIONS = {
    # Owner should normally be is_superuser=True.
    # This group is kept for label / backup permission use.
    "BUBU Owner": [
        "can_view_cost_price",
        "can_edit_cost_price",
    ],

    "BUBU Manager": [
        "can_view_cost_price",
        "can_edit_cost_price",

        # Inventory
        "view_item",
        "add_item",
        "change_item",
        "view_itemvariant",
        "add_itemvariant",
        "change_itemvariant",
        "view_stockmovement",
        "add_stockmovement",
        "change_stockmovement",
        "view_branchstock",

        # POS
        "view_sale",
        "add_sale",
        "change_sale",
        "view_saleitem",
        "add_saleitem",
        "change_saleitem",
        "view_salepayment",
        "add_salepayment",
        "change_salepayment",

        # Customer
        "view_customer",
        "add_customer",
        "change_customer",

        # Pets
        "view_pet",
        "add_pet",
        "change_pet",
        "view_petsale",
        "add_petsale",
        "change_petsale",

        # Staff / salary
        "view_staffattendance",
        "add_staffattendance",
        "change_staffattendance",
        "view_staffpayrollsetting",
        "add_staffpayrollsetting",
        "change_staffpayrollsetting",
        "view_staffcommission",
        "add_staffcommission",
        "change_staffcommission",
        "view_payrollrecord",
        "add_payrollrecord",
        "change_payrollrecord",
    ],

    "BUBU Sale": [
        # Can enter cost when needed, but cannot view costing/profit.
        # Do NOT add can_view_cost_price to this group.
        "can_edit_cost_price",

        # POS
        "view_sale",
        "add_sale",
        "change_sale",
        "view_saleitem",
        "add_saleitem",
        "change_saleitem",
        "view_salepayment",
        "add_salepayment",
        "change_salepayment",

        # Inventory basic
        "view_item",
        "add_item",
        "change_item",
        "view_itemvariant",
        "add_itemvariant",
        "change_itemvariant",
        "view_stockmovement",
        "add_stockmovement",
        "view_branchstock",

        # Customer
        "view_customer",
        "add_customer",
        "change_customer",

        # Pet sale
        "view_pet",
        "view_petsale",
        "add_petsale",
        "change_petsale",
    ],

    "BUBU Inventory": [
        # Can enter cost when stock in, but cannot see profit/cost reports.
        "can_edit_cost_price",

        "view_item",
        "add_item",
        "change_item",
        "view_itemvariant",
        "add_itemvariant",
        "change_itemvariant",
        "view_stockmovement",
        "add_stockmovement",
        "change_stockmovement",
        "view_branchstock",
    ],

    "BUBU Groomer": [
        "view_staffattendance",
        "add_staffattendance",
    ],
}


class Command(BaseCommand):
    help = "Create BUBU default staff roles/groups and cost permissions."

    def ensure_custom_permissions(self):
        content_type = ContentType.objects.get_for_model(Item)

        for codename, name in CUSTOM_INVENTORY_PERMISSIONS:
            Permission.objects.get_or_create(
                codename=codename,
                content_type=content_type,
                defaults={"name": name},
            )

    def handle(self, *args, **options):
        self.ensure_custom_permissions()

        all_permissions = {
            permission.codename: permission
            for permission in Permission.objects.select_related("content_type").all()
        }

        for role_name, codenames in ROLE_PERMISSIONS.items():
            group, created = Group.objects.get_or_create(name=role_name)
            group.permissions.clear()

            added = 0
            missing = []

            for codename in codenames:
                permission = all_permissions.get(codename)

                if permission:
                    group.permissions.add(permission)
                    added += 1
                else:
                    missing.append(codename)

            self.stdout.write(
                self.style.SUCCESS(
                    f"{'Created' if created else 'Updated'} {role_name}: {added} permissions"
                )
            )

            if missing:
                self.stdout.write(
                    self.style.WARNING(
                        f"Missing permissions for {role_name}: {', '.join(missing)}"
                    )
                )

        self.stdout.write(self.style.SUCCESS("BUBU roles created successfully."))
