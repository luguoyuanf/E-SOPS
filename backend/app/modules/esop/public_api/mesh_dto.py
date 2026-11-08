"""Terminal maintenance-network enrollment contract."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MeshEnrollmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MeshEnrollmentPublic(BaseModel):
    controlUrl: str
    authKey: str = Field(repr=False)
    expiresAt: datetime
