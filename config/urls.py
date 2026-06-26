from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView


urlpatterns = [
    # Browser fallback favicon.
    # Keep this first so /favicon.ico always redirects to the known working PNG.
    path(
        "favicon.ico",
        RedirectView.as_view(
            url="/static/img/bubu-favicon-32.png?v=20260626-31",
            permanent=False,
        ),
        name="favicon",
    ),

    path("admin/", admin.site.urls),

    # Main apps
    path("", include("core.urls")),
    path("users/", include("users.urls")),
    path("inventory/", include("inventory.urls")),
    path("customers/", include("customers.urls")),
    path("pos/", include("pos.urls")),
    path("delivery/", include("delivery.urls")),
    path("purchases/", include("purchases.urls")),
    path("services/", include("services.urls")),
    path("pets/", include("pets.urls")),

    # Staff attendance / payroll / commission
    path("staffs/", include("staffs.urls")),

    # Authentication
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="users/login.html",
        ),
        name="login",
    ),
    path(
        "logout/",
        auth_views.LogoutView.as_view(
            next_page="login",
        ),
        name="logout",
    ),
]


# Local development only.
# In production, Nginx should normally serve /static/ and /media/.
if settings.DEBUG:
    urlpatterns += static(
        settings.STATIC_URL,
        document_root=settings.STATIC_ROOT,
    )

    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )
