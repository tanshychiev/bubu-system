from django.urls import path
from . import views

urlpatterns = [
    path("", views.user_list, name="user_list"),
    path("add/", views.user_create, name="user_create"),
    path("<int:pk>/edit/", views.user_edit, name="user_edit"),
    path("<int:pk>/toggle-active/", views.user_toggle_active, name="user_toggle_active"),

    path("roles/", views.role_list, name="role_list"),
    path("roles/add/", views.role_create, name="role_create"),
    path("roles/<int:pk>/edit/", views.role_edit, name="role_edit"),

    path("permissions/", views.permission_list, name="permission_list"),
    path("roles/<int:pk>/delete/", views.role_delete, name="role_delete"),

    path("login/", views.user_login, name="login"),
    path("logout/", views.user_logout, name="logout"),
]