# In staffs/urls.py change:
# from . import views
# to:
from . import views, work_views

# Add these paths inside urlpatterns:
path("work/my/", work_views.grooming_my_work, name="grooming_my_work"),
path("work/<int:pk>/delete/", work_views.grooming_work_delete, name="grooming_work_delete"),
path("work/comparison/", work_views.grooming_daily_comparison, name="grooming_daily_comparison"),
path("work/comparison/helper/add/", work_views.grooming_helper_add, name="grooming_helper_add"),
path("work/comparison/confirm/", work_views.grooming_confirm_day, name="grooming_confirm_day"),
path("work/settings/", work_views.grooming_work_settings, name="grooming_work_settings"),
path("work/commission-rules/", work_views.staff_work_commission_rules, name="staff_work_commission_rules"),
path("salary/adjustments/", work_views.payroll_adjustment_list, name="payroll_adjustment_list"),
