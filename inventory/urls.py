from django.urls import path

from . import stock_count_views, views


urlpatterns = [
    # ==================================================
    # MAIN INVENTORY
    # ==================================================
    path(
        "",
        views.item_list,
        name="item_list",
    ),

    # ==================================================
    # CONTROL CENTER
    # ==================================================
    path(
        "control-center/",
        views.inventory_control_center,
        name="inventory_control_center",
    ),

    # ==================================================
    # BRANCH / SHOP
    # ==================================================
    path(
        "branches/",
        views.branch_list,
        name="branch_list",
    ),
    path(
        "branches/<int:pk>/delete/",
        views.branch_delete,
        name="branch_delete",
    ),
    path(
        "branches/<int:pk>/toggle/",
        views.branch_toggle,
        name="branch_toggle",
    ),

    # ==================================================
    # CREATE ITEM / TYPE / UNIT
    # ==================================================
    path(
        "create/",
        views.item_create,
        name="item_create",
    ),
    path(
        "types/create/",
        views.item_type_create,
        name="item_type_create",
    ),
    path(
        "types/<int:pk>/delete/",
        views.item_type_delete,
        name="item_type_delete",
    ),
    path(
        "units/<int:pk>/delete/",
        views.unit_option_delete,
        name="unit_option_delete",
    ),

    # ==================================================
    # STOCK IN + SEARCH API
    # ==================================================
    path(
        "stock/batch-in/",
        views.stock_batch_in,
        name="stock_batch_in",
    ),
    path(
        "api/variant-search/",
        views.variant_search_api,
        name="variant_search_api",
    ),

    # ==================================================
    # MOBILE STOCK COUNT
    # Keep these routes before the general <int:pk> item routes.
    # ==================================================
    path(
        "stock/count/",
        stock_count_views.stock_count_list,
        name="stock_count_list",
    ),
    path(
        "stock/count/start/",
        stock_count_views.stock_count_start,
        name="stock_count_start",
    ),
    path(
        "stock/count/<int:pk>/",
        stock_count_views.stock_count_detail,
        name="stock_count_detail",
    ),
    path(
        "stock/count/<int:pk>/line/<int:line_id>/save/",
        stock_count_views.stock_count_save_line,
        name="stock_count_save_line",
    ),
    path(
        "stock/count/<int:pk>/fill-remaining/",
        stock_count_views.stock_count_fill_remaining,
        name="stock_count_fill_remaining",
    ),
    path(
        "stock/count/<int:pk>/submit/",
        stock_count_views.stock_count_submit,
        name="stock_count_submit",
    ),
    path(
        "stock/count/<int:pk>/confirm/",
        stock_count_views.stock_count_confirm,
        name="stock_count_confirm",
    ),
    path(
        "stock/count/<int:pk>/cancel/",
        stock_count_views.stock_count_cancel,
        name="stock_count_cancel",
    ),

    # ==================================================
    # VARIANT
    # Keep these routes before the general <int:pk> item route.
    # ==================================================
    path(
        "variant/<int:variant_id>/stock/",
        views.variant_stock_movement,
        name="variant_stock_movement",
    ),
    path(
        "variant/<int:variant_id>/barcode/",
        views.variant_barcode_label,
        name="variant_barcode_label",
    ),
    path(
        "<int:pk>/variants/reorder/",
        views.item_variant_reorder,
        name="item_variant_reorder",
    ),
    path(
        "<int:pk>/variant/<int:variant_id>/edit/",
        views.item_variant_edit,
        name="item_variant_edit",
    ),
    path(
        "<int:pk>/variant/<int:variant_id>/delete/",
        views.item_variant_delete,
        name="item_variant_delete",
    ),

    # ==================================================
    # ITEM
    # These general routes must stay at the bottom.
    # ==================================================
    path(
        "<int:pk>/",
        views.item_detail,
        name="item_detail",
    ),
    path(
        "<int:pk>/edit/",
        views.item_edit,
        name="item_edit",
    ),
    path(
        "<int:pk>/delete/",
        views.item_delete,
        name="item_delete",
    ),
    path(
        "<int:pk>/variant/create/",
        views.item_variant_create,
        name="item_variant_create",
    ),
]