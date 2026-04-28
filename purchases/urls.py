from django.urls import path
from . import views

urlpatterns = [
    # 📦 Purchase
    path("", views.purchase_list, name="purchase_list"),
    path("create/", views.purchase_create, name="purchase_create"),
    path("<int:pk>/", views.purchase_detail, name="purchase_detail"),
    path("<int:pk>/edit/", views.purchase_update, name="purchase_update"),
    path("<int:pk>/delete/", views.purchase_delete, name="purchase_delete"),

    # 📥 Supplier Receive (NO branch)
    path("items/<int:item_id>/receive/", views.purchase_receive, name="purchase_receive"),

    # 🏪 Allocate to branch
    path("items/<int:item_id>/allocate/", views.purchase_allocate, name="purchase_allocate"),

    # 🚚 Transfer between branches
    path("items/<int:item_id>/transfer/", views.purchase_transfer_create, name="purchase_transfer_create"),

    # ✅ Transfer receive confirm
    path("transfers/<int:transfer_id>/receive/", views.purchase_transfer_receive, name="purchase_transfer_receive"),
]