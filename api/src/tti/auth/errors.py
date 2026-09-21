"""Auth rejections. Each carries a stable `code` for the API response body —
"zero matches and more than one match are both hard failures with distinct
error messages, because they have different fixes." (step 1.3)"""

from __future__ import annotations


class AuthError(Exception):
    code: str = "auth_error"


class ForeignDomainRejected(AuthError):
    code = "foreign_domain"


class UnverifiedEmailRejected(AuthError):
    code = "email_unverified"


class EmployeeNotFound(AuthError):
    code = "employee_not_found"


class EmployeeAmbiguous(AuthError):
    code = "employee_ambiguous"
