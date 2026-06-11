"""Development/testing tools for the Tiger Motors deployment."""


def __getattr__(name):
    """Lazy import to avoid circular import issues when running as __main__."""
    if name == "DataGenerator":
        from .data_generator import DataGenerator

        return DataGenerator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["DataGenerator"]
