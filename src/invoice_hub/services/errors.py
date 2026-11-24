"""Errors shared by AppState and the domain services split out of it (ENG-03)."""


class StaleInvoiceSelectionError(Exception):
    """A homepage selection no longer matches the active directory or its source files."""


class UnsupportedStartupSurfaceError(ValueError):
    """The requested startup surface is not available in this package (e.g. Windows portable)."""
