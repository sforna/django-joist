"""Demo project settings for the static showcase published on sforna.im.

Deliberately small: SQLite, no admin, DEBUG on so django-joist is enabled
without extra switches. The point of this project is the *schema* (four apps,
~30 models, plus deliberate doctor-bait) - the demo build script replays the
migrations in two steps so the dashboard's "changes since last migration"
panel has something real to show.
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = "joist-demo-not-a-secret"
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "catalog",
    "inventory",
    "sales",
    "support",
    "django_joist",
]

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
]

ROOT_URLCONF = "proj.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "var" / "demo.sqlite3",
    },
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
STATIC_URL = "static/"

# Business meaning a type cannot carry: shown by the exports, and a real
# install would also read native database comments here.
JOIST = {
    "annotations": {
        "notes": ["Synthetic schema for the public demo - no real data, ever."],
        "tables": {
            "sales_order": "One row per customer order, independent of fulfilment.",
            "inventory_stockitem": "Quantity on hand per warehouse and variant.",
        },
        "columns": {
            "sales_order.total_cents": "Order total in minor units, before tax.",
            "inventory_stockitem.reserved": "Held by open orders, not yet shipped.",
        },
    },
}
