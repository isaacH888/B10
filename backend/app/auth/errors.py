"""Safe public authentication errors."""


class AuthError(Exception):
    def __init__(self, code, message, status=401):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def unavailable():
    return AuthError("authentication_unavailable", "Authentication is temporarily unavailable. Please try again later.", 503)
