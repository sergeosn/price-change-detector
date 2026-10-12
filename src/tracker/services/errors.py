class NotFoundError(Exception):
    """The requested object does not exist."""


class DuplicateError(Exception):
    """An object with the same unique key already exists."""
