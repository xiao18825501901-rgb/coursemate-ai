class DocumentLoadError(Exception):
    """A safe, typed document loading failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
