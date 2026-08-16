from datetime import datetime, timezone
from typing import Annotated, TypeAlias

from pydantic import AfterValidator, Field, StringConstraints


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include a timezone")
    return value.astimezone(timezone.utc)


IdempotencyKey: TypeAlias = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
UtcDateTime: TypeAlias = Annotated[datetime, AfterValidator(_as_utc)]
MediaMilliseconds: TypeAlias = Annotated[int, Field(ge=0)]
