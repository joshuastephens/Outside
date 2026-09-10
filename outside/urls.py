"""Root URL configuration.

The API lives under /api/ so that / stays free for the optional server-rendered
page described in CLAUDE.md. Until that exists, / redirects to the endpoint's
Browsable API.
"""

from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("", RedirectView.as_view(url="/api/apod/", permanent=False)),
    path("api/", include("apod.urls")),
    path("admin/", admin.site.urls),
]
