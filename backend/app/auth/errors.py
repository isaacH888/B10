"""Safe public authentication errors."""


class AuthError(Exception):
    def __init__(self, code, message, status=401, *, reason=None, diagnostics=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        # Static diagnostic labels stay in private logs/audits, never responses.
        self.reason = reason
        self.diagnostics = diagnostics


def unavailable():
    return AuthError(
        "authentication_unavailable",
        "Authentication is temporarily unavailable. Please try again later.",
        503,
    )
