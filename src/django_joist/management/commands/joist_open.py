"""Open the Joist dashboard in the default browser.

The URL is built from the mounted route plus a configurable base
(``JOIST["base_url"]``, defaulting to Django's runserver address). On a
headless host the URL is printed regardless, so it can be opened by hand or
port-forwarded, and a note is shown when Joist is not enabled in the current
environment.
"""

from __future__ import annotations

import subprocess
import sys

from django.core.management.base import BaseCommand
from django.urls import NoReverseMatch, reverse

from django_joist.conf import joist_settings


class Command(BaseCommand):
    help = "Open the Joist dashboard in your browser."

    def handle(self, *args, **options):
        try:
            path = reverse("joist:index")
        except NoReverseMatch:
            self.stderr.write(
                self.style.ERROR(
                    'The joist:index route was not found. Mount it in your root URLconf: '
                    'path("joist/", include("django_joist.urls"))'
                )
            )
            return 1

        base = (joist_settings.get("base_url") or "http://127.0.0.1:8000").rstrip("/")
        url = f"{base}{path}"
        self.stdout.write(f"Joist: {self.style.SUCCESS(url)}")

        if not joist_settings.get("enabled"):
            self.stdout.write(
                self.style.WARNING(
                    "Joist is not enabled in this environment; set JOIST['enabled'] = True "
                    "(it follows DEBUG by default)."
                )
            )

        opener = {
            "darwin": ["open", url],
            "win32": ["cmd", "/c", "start", "", url],
        }.get(sys.platform, ["xdg-open", url])
        try:
            subprocess.run(opener, check=False, timeout=10, capture_output=True)
        except (OSError, subprocess.SubprocessError):
            pass  # headless host: the printed URL is the product
        return 0
