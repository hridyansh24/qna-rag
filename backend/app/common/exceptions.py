import structlog
from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = structlog.get_logger()


class QnaError(Exception):
    """Base application error."""

    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class NotFoundError(QnaError):
    def __init__(self, message: str = "Resource not found"):
        super().__init__("NOT_FOUND", message, status.HTTP_404_NOT_FOUND)


class ForbiddenError(QnaError):
    def __init__(self, message: str = "Forbidden"):
        super().__init__("FORBIDDEN", message, status.HTTP_403_FORBIDDEN)


class UnauthorizedError(QnaError):
    def __init__(self, message: str = "Unauthorized"):
        super().__init__("UNAUTHORIZED", message, status.HTTP_401_UNAUTHORIZED)


class ConflictError(QnaError):
    def __init__(self, message: str = "Conflict"):
        super().__init__("CONFLICT", message, status.HTTP_409_CONFLICT)


class PayloadTooLargeError(QnaError):
    def __init__(self, message: str = "Payload too large"):
        super().__init__(
            "PAYLOAD_TOO_LARGE", message, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        )


class RagError(QnaError):
    """
    An error from the RAG feature (ingestion, retrieval, generation) that
    carries its own HTTP status, so callers like /rag/compare can return the
    4xx/503 the design specifies (docs/design-rag.md §9.1) in the same JSON
    shape as every other QnaError.
    """

    def __init__(self, message: str, status_code: int, code: str = "RAG_ERROR"):
        super().__init__(code, message, status_code)


class RagServiceUnavailableError(RagError):
    """Ollama, Infinity or ChromaDB couldn't be reached, or failed (503)."""

    def __init__(self, message: str):
        super().__init__(
            message, status.HTTP_503_SERVICE_UNAVAILABLE, "RAG_SERVICE_UNAVAILABLE"
        )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(QnaError)
    async def qna_error_handler(request: Request, exc: QnaError) -> JSONResponse:
        logger.warning(
            "app_error", code=exc.code, message=exc.message, path=str(request.url)
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.code, "message": exc.message},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # jsonable_encoder matters here, not just style: a validator that
        # raises a plain ValueError (e.g. LoginRequest.check_credentials)
        # produces an errors() entry whose ctx.error is the raw exception
        # object — passing that straight to JSONResponse crashes json.dumps
        # with "Object of type ValueError is not JSON serializable", turning
        # what should be a 422 into an unhandled 500.
        errors = jsonable_encoder(exc.errors())
        logger.warning("validation_error", errors=errors, path=str(request.url))
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"error": "VALIDATION_ERROR", "detail": errors},
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled_error", exc_info=exc, path=str(request.url))
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
            },
        )
