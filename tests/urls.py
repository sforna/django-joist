from django.urls import include, path

from django_joist.views import embedded_dashboard


def host_embedded_page(request):
    """A host's own view serving the dashboard with its payload embedded, the
    way the README shows it. Ungated here; a real host gates it."""
    return embedded_dashboard(request, request.GET.get("connection") or None)


urlpatterns = [
    path("joist/", include("django_joist.urls")),
    path("host/embedded/", host_embedded_page, name="host_embedded"),
]
