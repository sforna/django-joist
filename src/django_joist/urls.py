"""Joist URLs. Mount wherever you like in the host project's root URLconf::

    from django.urls import include, path

    urlpatterns = [
        path("joist/", include("django_joist.urls")),
    ]

Every route is protected by the package itself (enabled switch + authorizer,
denials return 404), so the mount point is a naming choice, not a security
boundary. The page and the API live under the same prefix; the browser
fetches relative to it.
"""

from django.urls import path

from . import views

app_name = "joist"

urlpatterns = [
    path("", views.index, name="index"),
    path("api/schema", views.schema_api, name="api_schema"),
    path("export/<str:fmt>", views.export, name="export"),
    path("theme.css", views.theme_css, name="theme"),
    path("assets/<str:file>", views.asset, name="asset"),
]
