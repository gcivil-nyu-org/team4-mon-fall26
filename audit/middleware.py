import threading

_thread_locals = threading.local()


def get_current_user():
    """The user behind the request being handled, if they are logged in."""
    user = getattr(_thread_locals, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        return user
    return None


class AuditMiddleware:
    """Remember the current user on a thread-local so signals can log them.

    Must run after AuthenticationMiddleware, which sets request.user.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _thread_locals.user = getattr(request, "user", None)
        try:
            return self.get_response(request)
        finally:
            _thread_locals.user = None
