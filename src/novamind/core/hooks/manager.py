"""Stub hooks manager for backward compatibility."""
class _HooksManager:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None

hooks = _HooksManager()
