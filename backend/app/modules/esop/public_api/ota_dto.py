"""Channel hardware and OTA package contracts."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.esop.public_api.dto import EntityCodeInput


class ChannelInput(EntityCodeInput):
    code: str | None = Field(default=None, max_length=50)
    name: str = Field(min_length=1, max_length=100)


class ChannelPublic(ChannelInput):
    code: str
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime | None = None


class HardwareInput(EntityCodeInput):
    channel_id: uuid.UUID
    code: str | None = Field(default=None, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    abi: str = Field(min_length=1, max_length=30)


class HardwarePublic(HardwareInput):
    code: str
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime | None = None


class OtaPackageInput(BaseModel):
    channel_id: uuid.UUID
    hardware_model_id: uuid.UUID
    version: str = Field(min_length=1, max_length=80)
    version_code: int = Field(default=0, ge=0)
    package_name: str = Field(default="", max_length=200)
    file_id: uuid.UUID
    release_notes: str = Field(default="", max_length=4000)


class OtaPackagePublic(OtaPackageInput):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    file_name: str = ""
    checksum_sha256: str
    file_size: int
    status: str
    published_at: datetime | None
    created_at: datetime


class OtaManifest(BaseModel):
    packageId: uuid.UUID
    channelCode: str
    hardwareCode: str
    abi: str
    version: str
    versionName: str
    versionCode: int
    package: str
    size: int
    checksumSha256: str
    sha256: str
    downloadUrl: str
    apkUrl: str
    publishedAt: datetime
