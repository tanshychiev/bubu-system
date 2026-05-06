from django.urls import path
from . import views

urlpatterns = [
    # POS
    path("", views.pos, name="pos"),
    path("switch-branch/", views.pos_switch_branch, name="pos_switch_branch"),

    # Cart
    path("add/<int:item_id>/", views.pos_add_cart, name="pos_add_cart"),
    path("add-variant/<int:item_id>/<int:variant_id>/", views.pos_add_variant_cart, name="pos_add_variant_cart"),

    path("plus/<str:cart_key>/", views.pos_plus_cart, name="pos_plus_cart"),
    path("minus/<str:cart_key>/", views.pos_minus_cart, name="pos_minus_cart"),
    path("remove/<str:cart_key>/", views.pos_remove_cart, name="pos_remove_cart"),

    path("clear/", views.pos_clear_cart, name="pos_clear_cart"),
    path("checkout/", views.pos_checkout, name="pos_checkout"),

    # Sales
    path("sales/", views.sale_list, name="sale_list"),
    path("sales/<int:pk>/", views.sale_detail, name="sale_detail"),
    path("sales/<int:pk>/payment/", views.sale_add_payment, name="sale_add_payment"),
    path("cash-count/", views.cash_count_dashboard, name="cash_count_dashboard"),

    # Settings
    path("settings/exchange-rate/", views.pos_exchange_rate, name="pos_exchange_rate"),
]