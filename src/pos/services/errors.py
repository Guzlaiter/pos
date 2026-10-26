"""Shared service exceptions."""

from __future__ import annotations


class ServiceError(RuntimeError):
    """Base class for user-facing business errors."""


class ValidationError(ServiceError):
    """Input failed validation; message is safe to show to the user."""


class AuthError(ServiceError):
    """Login failed."""


class SaleError(ServiceError):
    """Sale could not be completed."""


class InsufficientStock(SaleError):
    """Not enough stock for a product."""


class ShiftError(ServiceError):
    """Shift operation failed."""


class ImportError_(ServiceError):
    """Legacy import failed."""
