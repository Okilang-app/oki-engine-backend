from http import HTTPStatus
from secrets import randbits
from time import time_ns
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

ERROR_BASE_URL = "https://errors.oki.app"
CORRELATION_ID_HEADER = "X-Correlation-ID"


def generate_correlation_id() -> str:
    """Generate an RFC 9562 UUIDv7 correlation identifier."""

    timestamp_ms = (time_ns() // 1_000_000) & ((1 << 48) - 1)
    random_bits = randbits(74)
    random_a = random_bits >> 62
    random_b = random_bits & ((1 << 62) - 1)
    value = (
        (timestamp_ms << 80)
        | (0x7 << 76)
        | (random_a << 64)
        | (0b10 << 62)
        | random_b
    )
    return str(UUID(int=value))


def parse_correlation_id(value: str | None) -> str | None:
    """Return a canonical UUIDv7 string, or None for any other identifier."""

    if value is None or len(value) > 36:
        return None
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        return None
    if parsed.version != 7:
        return None
    return str(parsed)


class Problem(BaseModel):
    """RFC 9457 problem details with stable Oki extensions."""

    model_config = ConfigDict(extra="forbid")

    type: str
    title: str
    status: int = Field(ge=400, le=599)
    detail: str
    instance: str | None = None
    code: str
    correlation_id: str
    field_errors: list[dict[str, str]] | None = None
    retryable: bool = False


class ProblemException(Exception):
    """A safe, client-visible application error."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        title: str,
        detail: str,
        type_uri: str | None = None,
        field_errors: list[dict[str, str]] | None = None,
        retryable: bool = False,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.title = title
        self.detail = detail
        self.type_uri = type_uri or f"{ERROR_BASE_URL}/{code}"
        self.field_errors = field_errors
        self.retryable = retryable
        self.headers = headers

class UnauthorizedProblem(ProblemException):
    """An authentication failure safe to expose through RFC 9457."""

    def __init__(self, *, code: str, detail: str) -> None:
        super().__init__(
            status_code=401,
            code=code,
            title="Unauthorized",
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


class ForbiddenProblem(ProblemException):
    """An authorization failure safe to expose through RFC 9457."""

    def __init__(self, *, code: str, detail: str) -> None:
        super().__init__(
            status_code=403,
            code=code,
            title="Forbidden",
            detail=detail,
        )


def _correlation_id(request: Request) -> str:
    correlation_id = parse_correlation_id(
        str(getattr(request.state, "correlation_id", "")),
    )
    if correlation_id is None:
        correlation_id = generate_correlation_id()
        request.state.correlation_id = correlation_id
    return correlation_id


def _problem_response(
    request: Request,
    *,
    status: int,
    code: str,
    title: str,
    detail: str,
    type_uri: str | None = None,
    field_errors: list[dict[str, str]] | None = None,
    retryable: bool = False,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    correlation_id = _correlation_id(request)
    problem = Problem(
        type=type_uri or f"{ERROR_BASE_URL}/{code}",
        title=title,
        status=status,
        detail=detail,
        instance=request.url.path,
        code=code,
        correlation_id=correlation_id,
        field_errors=field_errors,
        retryable=retryable,
    )
    response_headers = dict(headers or {})
    response_headers[CORRELATION_ID_HEADER] = correlation_id
    return JSONResponse(
        status_code=status,
        content=problem.model_dump(mode="json", exclude_none=True),
        headers=response_headers,
        media_type="application/problem+json",
    )


async def _problem_exception_handler(
    request: Request,
    exception: ProblemException,
) -> JSONResponse:
    return _problem_response(
        request,
        status=exception.status_code,
        code=exception.code,
        title=exception.title,
        detail=exception.detail,
        type_uri=exception.type_uri,
        field_errors=exception.field_errors,
        retryable=exception.retryable,
        headers=exception.headers,
    )


def _status_title(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "HTTP error"


def _status_code(status_code: int) -> str:
    return {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "resource_not_found",
        405: "method_not_allowed",
        409: "conflict",
        422: "validation_failed",
        429: "rate_limited",
    }.get(status_code, "http_error")


async def _http_exception_handler(
    request: Request,
    exception: StarletteHTTPException,
) -> JSONResponse:
    title = _status_title(exception.status_code)
    detail = exception.detail if isinstance(exception.detail, str) else title
    return _problem_response(
        request,
        status=exception.status_code,
        code=_status_code(exception.status_code),
        title=title,
        detail=detail,
        headers=exception.headers,
    )


async def _validation_exception_handler(
    request: Request,
    exception: RequestValidationError,
) -> JSONResponse:
    field_errors = [
        {
            "field": ".".join(str(part) for part in error["loc"]),
            "message": str(error["msg"]),
            "type": str(error["type"]),
        }
        for error in exception.errors()
    ]
    return _problem_response(
        request,
        status=422,
        code="validation_failed",
        title="Validation failed",
        detail="The request contains invalid data.",
        field_errors=field_errors,
    )


def internal_server_error_response(request: Request) -> JSONResponse:
    """Build a safe problem response for an unexpected application error."""

    return _problem_response(
        request,
        status=500,
        code="internal_server_error",
        title="Internal server error",
        detail="The server could not complete the request.",
        retryable=True,
    )


def register_problem_handlers(app: FastAPI) -> None:
    """Register application and framework exception translations."""

    app.add_exception_handler(ProblemException, _problem_exception_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
