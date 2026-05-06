from django.urls import path
from . import views

urlpatterns = [
    path("", views.pet_list, name="pet_list"),

    path("create/", views.pet_create, name="pet_create"),
    path("<int:pk>/", views.pet_detail, name="pet_detail"),
    path("<int:pk>/edit/", views.pet_edit, name="pet_edit"),

    path("sales/create/", views.pet_sale_create, name="pet_sale_create"),
    path("sales/<int:pk>/", views.pet_sale_detail, name="pet_sale_detail"),
    path("sales/<int:pk>/edit/", views.pet_sale_edit, name="pet_sale_edit"),

    path("sales/<int:pk>/arrived/", views.pet_sale_mark_arrived, name="pet_sale_mark_arrived"),
    path("sales/<int:pk>/complete/", views.pet_sale_complete, name="pet_sale_complete"),
    path("sales/<int:pk>/cancel/", views.pet_sale_cancel, name="pet_sale_cancel"),
    path("sales/<int:pk>/refund/", views.pet_sale_refund, name="pet_sale_refund"),

    path("sales/<int:pk>/warranty/print/", views.pet_warranty_print, name="pet_warranty_print"),
    path("sales/<int:pk>/receipt/print/", views.pet_sale_receipt_print, name="pet_sale_receipt_print"),

    path("sales/<int:sale_id>/warranty-claim/create/", views.pet_warranty_claim_create, name="pet_warranty_claim_create"),
]