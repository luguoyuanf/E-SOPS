"""Editable display content; independent of granted storage and device entitlements."""
from pydantic import BaseModel, ConfigDict, Field


class PurchasePrice(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    customer: str = Field(min_length=1, max_length=100)
    quantity: str = Field(min_length=1, max_length=100)
    price: str = Field(min_length=1, max_length=100)


class PurchasePageContent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(default="购买与扩容", min_length=1, max_length=100)
    contact_text: str = Field(default="购买设备授权或扩容存储，请联系客户经理微信。", min_length=1, max_length=2000)
    device_title: str = Field(default="设备授权", min_length=1, max_length=100)
    device_description: str = Field(default="设备密钥激活后可永久使用。企业注册后可领取一个免费激活密钥。", min_length=1, max_length=4000)
    prices: list[PurchasePrice] = Field(default_factory=lambda: [
        PurchasePrice(customer="企业", quantity="1–50 台", price="50 元 / 台"),
        PurchasePrice(customer="企业", quantity="51–100 台", price="45 元 / 台"),
        PurchasePrice(customer="企业", quantity="101 台及以上", price="40 元 / 台"),
        PurchasePrice(customer="渠道", quantity="100 台及以上", price="30 元 / 台"),
    ], max_length=30)
    storage_title: str = Field(default="云端存储", min_length=1, max_length=100)
    storage_description: str = Field(default="新租户初始云端存储容量由平台管理员统一配置。需要更多容量时，可联系客户经理微信购买按年存储包。", min_length=1, max_length=4000)
    storage_note: str = Field(default="具体存储包容量与价格请咨询客户经理。", max_length=2000)
