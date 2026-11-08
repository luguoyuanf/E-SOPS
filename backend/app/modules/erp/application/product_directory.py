"""Tenant-checked implementation of the ERP product lookup contract."""

import uuid

from sqlmodel import Session, col, select

from app.modules.erp.infrastructure.models import Product, ProductCategory
from app.modules.erp.infrastructure.tenant_uow import ErpTenantUnitOfWork
from app.modules.erp.public_api.products import ProductCategorySummary, ProductSummary


class SqlProductDirectory:
    def __init__(self, session: Session, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    def exists(self, product_id: uuid.UUID) -> bool:
        return self.get(product_id) is not None

    def get(self, product_id: uuid.UUID) -> ProductSummary | None:
        with ErpTenantUnitOfWork(self._session, self._tenant_id):
            product = self._session.get(Product, product_id)
            if product is None or product.tenant_id != self._tenant_id:
                return None
            category = self._session.get(ProductCategory, product.category_id) if product.category_id else None
            return ProductSummary(
                id=product.id, code=product.code, name=product.name, category_id=product.category_id, model=product.model,
                category_name=category.name if category and category.tenant_id == self._tenant_id else "",
            )

    def list(self, keyword: str | None = None) -> list[ProductSummary]:
        with ErpTenantUnitOfWork(self._session, self._tenant_id):
            statement = select(Product).where(Product.is_active == True)  # noqa: E712
            if keyword:
                pattern = f"%{keyword.strip()}%"
                statement = statement.where(
                    col(Product.code).ilike(pattern) | col(Product.name).ilike(pattern)
                )
            products = self._session.exec(
                statement.order_by(Product.name).limit(100)
            ).all()
            return [
                ProductSummary(id=product.id, code=product.code, name=product.name, category_id=product.category_id, model=product.model)
                for product in products
            ]

    def tree(self) -> tuple[list[ProductCategorySummary], list[ProductSummary]]:
        with ErpTenantUnitOfWork(self._session, self._tenant_id):
            categories = self._session.exec(
                select(ProductCategory).order_by(ProductCategory.sort, ProductCategory.name)
            ).all()
            products = self._session.exec(
                select(Product).where(Product.is_active == True).order_by(Product.name)  # noqa: E712
            ).all()
            return (
                [ProductCategorySummary(id=c.id, name=c.name, parent_id=c.parent_id) for c in categories],
                [ProductSummary(id=p.id, code=p.code, name=p.name, category_id=p.category_id, model=p.model) for p in products],
            )
