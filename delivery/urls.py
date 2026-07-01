from django.urls import path

from . import views


urlpatterns = [
    path("", views.delivery_list, name="delivery_list"),
    path("create/", views.delivery_create, name="delivery_create"),
    path("cod-report/", views.delivery_cod_report, name="delivery_cod_report"),
    path("customer-lookup/", views.delivery_customer_lookup, name="delivery_customer_lookup"),

    path("companies/", views.delivery_company_list, name="delivery_company_list"),
    path("companies/create/", views.delivery_company_create, name="delivery_company_create"),
    path("companies/<int:pk>/edit/", views.delivery_company_update, name="delivery_company_update"),
    path("companies/<int:pk>/toggle/", views.delivery_company_toggle, name="delivery_company_toggle"),

    path("<int:pk>/", views.delivery_detail, name="delivery_detail"),
    path("<int:pk>/edit/", views.delivery_update, name="delivery_update"),
    path("<int:pk>/delete/", views.delivery_delete, name="delivery_delete"),
    path("<int:pk>/sticker/", views.delivery_sticker, name="delivery_sticker"),
    path("<int:pk>/mark-out/", views.delivery_mark_out, name="delivery_mark_out"),
    path("<int:pk>/mark-done/", views.delivery_mark_done, name="delivery_mark_done"),
    path("<int:pk>/mark-failed/", views.delivery_mark_failed, name="delivery_mark_failed"),
    path("<int:pk>/return-stock/", views.delivery_return_stock, name="delivery_return_stock"),
    path("<int:pk>/confirm-cod/", views.delivery_confirm_cod, name="delivery_confirm_cod"),
    path("<int:pk>/settle-cod/", views.delivery_settle_cod, name="delivery_settle_cod"),
]
