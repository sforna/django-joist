"""Joist URLs. Mount with: path("joist/", include("django_joist.urls")).

Populated by the HTTP layer task; kept importable meanwhile so the test
URLconf loads.
"""

from django.urls import path

app_name = "joist"

urlpatterns: list = []
