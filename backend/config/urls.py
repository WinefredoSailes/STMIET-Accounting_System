"""Root URL configuration.

Versioned API namespace: /api/v1/ per ADR-010 (API-first). Schema at /api/schema.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

API_PREFIX = "api/v1"

urlpatterns = [
    path("admin/", admin.site.urls),
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
        f"{API_PREFIX}/workflow/",
        include("apps.workflow.urls"),
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
