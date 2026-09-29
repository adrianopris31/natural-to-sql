"""Application custom exceptions mapped to user-friendly messages."""


class AppError(Exception):
    """Base application exception."""

    def __init__(self, message: str, user_message: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.user_message = user_message or message


class ValidationError(AppError):
    """Raised when SQL validation fails security or safety checks."""

    def __init__(self, message: str, user_message: str | None = None) -> None:
        friendly = user_message or f"Query validation failed: {message}"
        super().__init__(message=message, user_message=friendly)


class ExecutionError(AppError):
    """Raised when SQL execution fails on the database."""

    def __init__(self, message: str, raw_error: str | None = None) -> None:
        friendly = f"Execution error: {message}"
        super().__init__(message=message, user_message=friendly)
        self.raw_error = raw_error


class LLMError(AppError):
    """Raised when Ollama LLM call fails or outputs invalid format."""

    def __init__(self, message: str, user_message: str | None = None) -> None:
        friendly = user_message or "Language model service error. Please try again."
        super().__init__(message=message, user_message=friendly)


class SchemaError(AppError):
    """Raised when schema introspection or lookup fails."""

    def __init__(self, message: str, user_message: str | None = None) -> None:
        friendly = user_message or f"Schema error: {message}"
        super().__init__(message=message, user_message=friendly)
