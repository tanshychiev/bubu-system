BUBU TWO-ROLE COST UPDATE — COMPLETE V2

Owner/Admin:
- sees real cost and pet-sale profit
- can add or replace cost

Staff:
- can add or replace cost
- never receives the saved cost amount in HTML, hidden inputs, or JavaScript
- sees only “No Cost” or “Already Added”

Updated:
- inventory item/variant/stock-in pages
- pet list/detail/create/edit/bulk stock-in
- breed master list/form
- available-for-sale pets
- pet sale form/list/detail
- customer receipt stays cost-free

Install:
1. Copy all folders into the matching BUBU project paths.
2. Run:
   python manage.py check
   python manage.py makemigrations --check
   sudo systemctl restart bubu

No database migration is required.

Still needed:
- templates/base.html
This is needed to hide Owner-only menus such as profit, payroll, and system settings from Staff.
