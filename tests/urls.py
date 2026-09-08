from django.urls import include, path

urlpatterns = [path("joist/", include("django_joist.urls"))]
