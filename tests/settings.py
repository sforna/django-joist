"""Test project settings for the django-joist suite.

SQLite is the local default; the PostgreSQL and MySQL lanes (CI jobs, and any
local run) select a real backend with ``JOIST_TEST_ENGINE`` plus connection
environment variables. Both aliases move to that backend together, on two
separate databases, so the multi-alias and isolation behaviour is exercised on
a real server too.
"""

import os

SECRET_KEY = "joist-tests-not-a-secret"
DEBUG = True
USE_TZ = True

#: sqlite (default), postgres or mysql.
_TEST_ENGINE = os.environ.get("JOIST_TEST_ENGINE", "sqlite")

if _TEST_ENGINE == "sqlite":
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
else:
    if _TEST_ENGINE == "mysql":
        # PyMySQL speaks the same protocol and registers itself as MySQLdb;
        # test-only, and it keeps the lane free of a C build.
        import pymysql

        pymysql.install_as_MySQLdb()
        _ENGINE = "django.db.backends.mysql"
        _DEFAULT_PORT = "3306"
    elif _TEST_ENGINE == "postgres":
        _ENGINE = "django.db.backends.postgresql"
        _DEFAULT_PORT = "5432"
    else:
        raise RuntimeError(f"JOIST_TEST_ENGINE={_TEST_ENGINE!r} is not sqlite, postgres or mysql")

    _SERVER = {
        "ENGINE": _ENGINE,
        "HOST": os.environ.get("JOIST_TEST_HOST", "127.0.0.1"),
        "PORT": os.environ.get("JOIST_TEST_PORT", _DEFAULT_PORT),
        "USER": os.environ.get("JOIST_TEST_USER", "joist"),
        "PASSWORD": os.environ.get("JOIST_TEST_PASSWORD", "password"),
    }
    DATABASES = {
        # Two databases on the same server: a snapshot, its exclusions and its
        # baseline are per alias, and a shared database would hide a leak.
        "default": {**_SERVER, "NAME": os.environ.get("JOIST_TEST_DB", "joist_test")},
        "secondary": {
            **_SERVER,
            "NAME": os.environ.get("JOIST_TEST_DB_SECONDARY", "joist_test_secondary"),
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

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
]
# Signed-cookie sessions: force_login needs a session store, and we do not
# want a django_session table in the test DB (it would also pollute snapshots).
SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

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
