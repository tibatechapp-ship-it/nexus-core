"""Stub tools module for backward compatibility."""
class _Registry:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None

registry = _Registry()
