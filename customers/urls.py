from django.urls import path
from . import views

urlpatterns = [
    path("", views.customer_list, name="customer_list"),
    path("create/", views.customer_create, name="customer_create"),
    path("<int:pk>/", views.customer_detail, name="customer_detail"),
    path("<int:pk>/edit/", views.customer_update, name="customer_update"),
    path("<int:pk>/delete/", views.customer_delete, name="customer_delete"),

    path("<int:customer_id>/pets/create/", views.customer_pet_create, name="customer_pet_create"),
    path("pets/<int:pk>/edit/", views.customer_pet_update, name="customer_pet_update"),
    path("pets/<int:pk>/delete/", views.customer_pet_delete, name="customer_pet_delete"),
]