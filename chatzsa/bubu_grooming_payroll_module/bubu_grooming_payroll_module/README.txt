BUBU GROOMING WORK + PAYROLL MODULE
===================================

WHAT THIS PACKAGE DOES
----------------------
1. Removes Groomer PIN and automatic grooming commission from POS.
2. POS keeps normal Sale and SaleItem quantities only.
3. Groomers record their own completed work in a separate page.
4. Groomers cannot see POS expected totals, other staff totals, or differences.
5. Admin compares POS expected work against staff + helper records.
6. Helper work never creates commission.
7. Each staff can have different commission rules.
8. Bonus, deduction, and salary advance records can be attached to payroll.
9. Existing payroll and attendance data remain intact.

FILES
-----
modified_files/pos_views.py
    Replacement for your current pos/views.py. Groomer PIN code is removed.

modified_files/pos.html
    Replacement for your current POS template. Groomer PIN box and JS validation are removed.

staffs_models_additions.py
    Append all models to the end of staffs/models.py.

work_views.py
    Save as staffs/work_views.py.

urls_additions.py
    Shows the import and URL paths to add to staffs/urls.py.

templates/staffs/*.html
    Copy to templates/staffs/.

base_menu_snippet.html
    Add inside the Staff submenu in templates/base.html.

payroll_integration.py
    Add the helper functions and marked blocks to staffs/views.py so approved work,
    bonuses, deductions and salary advances are included when opening payroll.

SAFE INSTALL ORDER
------------------
1. Back up the project and database.
2. Copy the new model classes to staffs/models.py.
3. Run:
       python manage.py makemigrations staffs
       python manage.py migrate
4. Copy staffs/work_views.py and the new templates.
5. Update staffs/urls.py using urls_additions.py.
6. Replace POS views/template with modified_files versions.
7. Add the Staff menu links from base_menu_snippet.html.
8. Apply payroll_integration.py to staffs/views.py.
9. Run:
       python manage.py check
10. Test locally before Git push.

FIRST SETTINGS TO CREATE
------------------------
Work types:
- Grooming (code: grooming)
- Showering (code: showering)
- Trimming (code: trimming)

Mappings:
- Full Grooming -> Grooming x1
- Full Grooming -> Showering x1
- Shower Only -> Showering x1
- Trimming -> Trimming x1
- Trimming -> Showering x1

IMPORTANT PERMISSIONS
---------------------
Normal staff:
- Can add/view/delete only their own draft work.
- Cannot access Daily Comparison.

Admin/Owner:
- Can see POS expected totals and differences.
- Can add helper work.
- Can confirm a day.
- Can manage mappings, commission rules, bonuses and deductions.
