"""Errors shared by AppState and the domain services split out of it (ENG-03)."""


class StaleInvoiceSelectionError(Exception):
    """A homepage selection no longer matches the active directory or its source files."""
