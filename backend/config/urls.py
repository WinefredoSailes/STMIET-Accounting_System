"""Root URL configuration.

Versioned API namespace: /api/v1/ per ADR-010 (API-first). Schema at /api/schema.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

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
        f"{API_PREFIX}/cash/",
        include("apps.cash.urls"),
    ),
    path(
        f"{API_PREFIX}/assets/",
        include("apps.assets.urls"),
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

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
