from django.urls import path
from . import views

urlpatterns = [
    path("", views.delivery_list, name="delivery_list"),
    path("create/", views.delivery_create, name="delivery_create"),
    path("<int:pk>/", views.delivery_detail, name="delivery_detail"),
    path("<int:pk>/edit/", views.delivery_update, name="delivery_update"),
    path("<int:pk>/delete/", views.delivery_delete, name="delivery_delete"),
    path("<int:pk>/sticker/", views.delivery_sticker, name="delivery_sticker"),
]