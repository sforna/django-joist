"""Test project settings for the django-joist suite."""

SECRET_KEY = "joist-tests-not-a-secret"
DEBUG = True
USE_TZ = True

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    },
    "secondary": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    },
}

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django_joist",
    "tests.testapp",
]

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "joist-tests",
    }
}

ROOT_URLCONF = "tests.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    }
]

JOIST = {}
