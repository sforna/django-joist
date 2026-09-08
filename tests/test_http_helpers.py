"""Helpers for tests that need a dotted-path authorizer."""


def staff_authorizer(request):
    user = getattr(request, "user", None)
    return bool(user and getattr(user, "is_authenticated", False) and user.is_staff)
