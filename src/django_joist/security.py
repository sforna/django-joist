"""The two independent access layers guarding every Joist route.

Ported from the reference's ``enabled`` switch + fixed ``viewTruss`` gate,
adapted to Django:

1. ``JOIST["enabled"]`` — when off, every route answers **404**, behaving as
   if it does not exist. Defaults to ``settings.DEBUG`` (the Django analog of
   "local environment"), so a production deploy is dark until you enable it.
2. The **authorizer** — the access control: "who may view". Consulted only
   when ``DEBUG`` is false (DEBUG is unconditionally open, like local). A
   denial returns **404**, not 403: the dashboard never confirms it exists to
   someone who may not see it.

The authorizer is a callable ``request -> bool``. By default it admits users
whose email is in ``JOIST["authorization"]["allowed_emails"]`` and **fails
closed** on an empty list. Hosts with richer needs (a role/permission check)
set ``JOIST["authorization"]["callable"]`` to a dotted path — that fully
replaces the default.

Django note: unlike the reference there is no configurable middleware stack,
because ``request.user`` is already resolved by the project's own middleware.
The host must therefore mount Joist's URLs inside a URLconf where the session
and auth middleware run (the normal case); the authorizer always runs after
them because it is part of the view, which cannot be configured away.
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest, Http404
from django.utils.module_loading import import_string

from .conf import joist_settings


def default_authorizer(request: HttpRequest) -> bool:
    """Admit authenticated users whose email is allow-listed. A guest resolves
    to ``None``/anonymous and is denied; an empty list denies everyone."""
    allowed = joist_settings.get("authorization.allowed_emails", []) or []
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    email = getattr(user, "email", None)
    return bool(email) and email in allowed


def resolve_authorizer() -> Callable[[HttpRequest], bool]:
    callback = joist_settings.get("authorization.callable")
    if callback is None:
        return default_authorizer
    if callable(callback):
        return callback
    if isinstance(callback, str):
        try:
            return import_string(callback)
        except ImportError as exc:  # a bad path must fail loudly, not silently deny
            raise ImproperlyConfigured(f"JOIST['authorization']['callable'] could not be imported: {exc}") from exc
    raise ImproperlyConfigured("JOIST['authorization']['callable'] must be a callable or dotted path.")


def joist_protected(view_func):
    """The fixed guard: enabled switch + authorizer, both denying with 404.

    Applied as a decorator on every Joist view; it cannot be configured away
    by the host, only the authorizer callback can be replaced.
    """

    @wraps(view_func)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any):
        if not joist_settings.get("enabled"):
            raise Http404
        if not getattr(settings, "DEBUG", False):
            try:
                allowed = resolve_authorizer()(request)
            except ImproperlyConfigured:
                raise
            if not allowed:
                raise Http404
        return view_func(request, *args, **kwargs)

    return wrapper
