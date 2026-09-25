"""Root URL configuration.

Versioned API namespace: /api/v1/ per ADR-010 (API-first). Schema at /api/schema.
"""

from django.contrib import admin
from django.urls import include, path, re_path

from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

API_PREFIX = "api/v1"

urlpatterns = [
    path("admin/", admin.site.urls),
    # Server-rendered UI (HTMX + Tailwind). Not versioned — it is the staff app.
    path("", include("apps.ui.urls")),
    # Auth (JWT for API consumers / machine-to-machine; session auth for the UI).
    path(f"{API_PREFIX}/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path(f"{API_PREFIX}/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path(
        "api/schema/",
        SpectacularAPIView.as_view(),
        name="schema",
    ),
    path(
        "api/schema/swagger-ui/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path(
        f"{API_PREFIX}/foundation/",
        include("apps.foundation.urls"),
    ),
    path(
        f"{API_PREFIX}/posting/",
        include("apps.posting.urls"),
    ),
    path(
        f"{API_PREFIX}/ar/",
        include("apps.ar.urls"),
    ),
    path(
        f"{API_PREFIX}/ap/",
        include("apps.ap.urls"),
    ),
    path(
        f"{API_PREFIX}/billing/",
        include("apps.billing.urls"),
    ),
    path(
        f"{API_PREFIX}/cash/",
        include("apps.cash.urls"),
    ),
    path(
        f"{API_PREFIX}/assets/",
        include("apps.assets.urls"),
    ),
    path(
        f"{API_PREFIX}/inventory/",
        include("apps.inventory.urls"),
    ),
    path(
        f"{API_PREFIX}/payroll/",
        include("apps.payroll.urls"),
    ),
    path(
        f"{API_PREFIX}/workflow/",
        include("apps.workflow.urls"),
    ),
    path(
        f"{API_PREFIX}/reporting/",
        include("apps.reporting.urls"),
    ),
]

# Uploaded media (profile avatars). Served in every environment, not just
# DEBUG: on Render the WhiteNoise layer only covers STATIC_ROOT, so without
# this route /media/... would 404 even when the file is present. Django's
# serve() restricts unsafe content types by default. Resolved through
# default_storage so an overridden storage backend (tests) stays coherent.
from django.core.files.storage import default_storage
from django.views.static import serve as _static_serve


def _media_serve(request, path):
    return _static_serve(request, path, document_root=default_storage.location)


urlpatterns += [
    re_path(r"^media/(?P<path>.*)$", _media_serve),
]
