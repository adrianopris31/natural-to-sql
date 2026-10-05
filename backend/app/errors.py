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


class KnowledgeBotError(AppError):
    """Base exception for knowledge base (Jira/Slack/docs) errors."""

    def __init__(
        self,
        message: str,
        user_message: str | None = None,
        status_code: int = 502,
    ) -> None:
        friendly = user_message or f"Knowledge base error: {message}"
        super().__init__(message=message, user_message=friendly)
        self.status_code = status_code


class KnowledgeBotNotConfiguredError(KnowledgeBotError):
    """Raised when knowledge-bot API key is not configured."""

    def __init__(
        self,
        message: str = "Knowledge base is not configured",
        user_message: str | None = None,
        status_code: int = 503,
    ) -> None:
        friendly = user_message or (
            "Documentation search is not configured. Please set KNOWLEDGE_BOT_API_KEY."
        )
        super().__init__(message=message, user_message=friendly, status_code=status_code)


class KnowledgeBotUnreachableError(KnowledgeBotError):
    """Raised when knowledge-bot service cannot be reached or times out."""

    def __init__(
        self,
        message: str = "Knowledge base service is unreachable",
        user_message: str | None = None,
        status_code: int = 503,
    ) -> None:
        friendly = user_message or (
            "Knowledge base service is unreachable or timed out. Please verify it is running."
        )
        super().__init__(message=message, user_message=friendly, status_code=status_code)


class KnowledgeBotAuthError(KnowledgeBotError):
    """Raised when knowledge-bot authentication (API key) fails (401/403)."""

    def __init__(
        self,
        message: str = "Knowledge base authentication failed",
        user_message: str | None = None,
        status_code: int = 401,
    ) -> None:
        friendly = user_message or "Knowledge base authentication failed. Check your API key."
        super().__init__(message=message, user_message=friendly, status_code=status_code)


class KnowledgeBotQuotaError(KnowledgeBotError):
    """Raised when knowledge-bot quota or rate limit is exceeded (429)."""

    def __init__(
        self,
        message: str = "Knowledge base quota exceeded",
        user_message: str | None = None,
        status_code: int = 429,
    ) -> None:
        friendly = user_message or (
            "Knowledge base quota or rate limit exceeded. Please try again later."
        )
        super().__init__(message=message, user_message=friendly, status_code=status_code)


class KnowledgeBotUpstreamError(KnowledgeBotError):
    """Raised when knowledge-bot upstream LLM service fails (502)."""

    def __init__(
        self,
        message: str = "Knowledge base upstream provider error",
        user_message: str | None = None,
        status_code: int = 502,
    ) -> None:
        friendly = user_message or "Knowledge base upstream AI service encountered an error."
        super().__init__(message=message, user_message=friendly, status_code=status_code)
