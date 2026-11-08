"""Tenant broadcast settings for top and bottom terminal tickers."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class BroadcastInput(BaseModel):
    content: str = Field(min_length=1, max_length=500)
    font_size: int = Field(ge=12, le=72)
    background_color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    font_color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    is_active: bool = True


class BroadcastPublic(BroadcastInput):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    position: Literal["top", "bottom"]
    updated_at: datetime


class ListBroadcasts(BaseModel):
    items: list[BroadcastPublic]
    total: int


class AdvertisementMedia(BaseModel):
    kind: Literal["text", "image", "video"]
    file_id: uuid.UUID | None = None
    content: str = Field(default="", max_length=2000)
    name: str = Field(default="", max_length=255)
    duration_seconds: int = Field(default=10, ge=1, le=3600)

    @model_validator(mode="after")
    def valid_media(self):
        if self.kind == "text":
            if not self.content.strip() or self.file_id is not None:
                raise ValueError("文字素材需填写内容且不能关联文件")
        elif self.file_id is None:
            raise ValueError("图片和视频必须上传文件")
        return self


class AdvertisementInput(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    layout: Literal["fullscreen", "left", "right", "top", "bottom"] = "fullscreen"
    playback: Literal["continuous", "interval"] = "continuous"
    interval_minutes: int = Field(default=30, ge=1, le=10080)
    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None
    daily_start: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    daily_end: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    media: list[AdvertisementMedia] = Field(min_length=1, max_length=50)
    is_active: bool = False

    @model_validator(mode="after")
    def valid_schedule(self):
        if not self.title.strip():
            raise ValueError("请填写广告名称")
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("结束时间必须晚于开始时间")
        if bool(self.daily_start) != bool(self.daily_end) or (self.daily_start and self.daily_start == self.daily_end):
            raise ValueError("每日时段需同时填写且开始与结束不能相同")
        return self


class AdvertisementPublic(AdvertisementInput):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    starts_at: datetime
    created_at: datetime
    updated_at: datetime


class ListAdvertisements(BaseModel):
    items: list[AdvertisementPublic]
    total: int


class BroadcastRecordPublic(BroadcastPublic):
    created_at: datetime


class ListBroadcastRecords(BaseModel):
    items: list[BroadcastRecordPublic]
    total: int
