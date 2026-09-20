"""Odoo error taxonomy — retry behaviour depends on it, see
docs/implementation-plan.md step 1.2."""

from __future__ import annotations


class OdooError(Exception):
    """Base for all Odoo client errors."""


class OdooUnavailable(OdooError):
    """Connection error, timeout before/while sending, or a 5xx response.
    Retryable."""


class OdooUncertain(OdooError):
    """The request was sent but the outcome is unknown (timeout after
    send, or the connection was lost while the response was in flight).
    Retryable only via the reconcile path, never by blind re-create."""


class OdooRejected(OdooError):
    """Odoo received the call and explicitly rejected it (ValidationError,
    UserError, AccessError, bad credentials, ...). Not retryable — needs a
    human."""

    def __init__(self, message: str, *, odoo_exception: str | None = None) -> None:
        super().__init__(message)
        self.odoo_exception = odoo_exception
