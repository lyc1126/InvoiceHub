from typing import Any


def create_app(*args: Any, **kwargs: Any):
    from .app import create_app as factory

    return factory(*args, **kwargs)

__all__ = ["create_app"]
