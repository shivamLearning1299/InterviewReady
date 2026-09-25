"""Generic pagination envelope shared by every catalog/listing endpoint."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Stable ``limit``/``offset`` pagination wrapper.

    ``total`` is the count *after* filters but *before* paging, so a client can render
    "showing 1-50 of 400" without a second request.
    """

    items: list[T] = Field(default_factory=list, description="Records for this page")
    total: int = Field(description="Total matching records, ignoring pagination")
    limit: int = Field(description="Maximum records that may be returned")
    offset: int = Field(description="Number of records skipped")

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


class MessageResponse(BaseModel):
    """Simple acknowledgement body for endpoints with no resource to return."""

    message: str
    detail: str | None = None


class DeletedResponse(BaseModel):
    """Body returned for a 200-with-body delete; 204 endpoints return nothing."""

    deleted: bool = True
    id: str
    message: str | None = None
