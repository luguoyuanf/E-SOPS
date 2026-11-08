"""Opaque completion tickets for browser-to-OSS operation image uploads."""

from pydantic import BaseModel, Field


class DirectFileTicket(BaseModel):
    ticket: str = Field(min_length=1, max_length=8192)
