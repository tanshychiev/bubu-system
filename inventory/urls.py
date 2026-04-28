from django.urls import path
from . import views

urlpatterns = [

    # =====================
    # MAIN
    # =====================
    path("", views.item_list, name="item_list"),

    # =====================
    # BRANCH / SHOP
    # =====================
    path("branches/", views.branch_list, name="branch_list"),
    path("branches/<int:pk>/delete/", views.branch_delete, name="branch_delete"),
    path("branches/<int:pk>/toggle/", views.branch_toggle, name="branch_toggle"),

    # =====================
    # CREATE
    # =====================
    path("create/", views.item_create, name="item_create"),
    path("types/create/", views.item_type_create, name="item_type_create"),

    # =====================
    # BATCH + API
    # =====================
    path("stock/batch-in/", views.stock_batch_in, name="stock_batch_in"),
    path("api/variant-search/", views.variant_search_api, name="variant_search_api"),

    # =====================
    # VARIANT (IMPORTANT: before <int:pk>)
    # =====================
    path("variant/<int:variant_id>/stock/", views.variant_stock_movement, name="variant_stock_movement"),
    path("variant/<int:variant_id>/barcode/", views.variant_barcode_label, name="variant_barcode_label"),
    path("<int:pk>/variant/<int:variant_id>/edit/", views.item_variant_edit, name="item_variant_edit"),
    path("<int:pk>/variant/<int:variant_id>/delete/", views.item_variant_delete, name="item_variant_delete"),

    # =====================
    # ITEM
    # =====================
    path("<int:pk>/", views.item_detail, name="item_detail"),
    path("<int:pk>/edit/", views.item_edit, name="item_edit"),
    path("<int:pk>/delete/", views.item_delete, name="item_delete"),
    path("<int:pk>/variant/create/", views.item_variant_create, name="item_variant_create"),
]