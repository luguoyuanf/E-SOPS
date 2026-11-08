"""Channel workspace navigation follows the channel administrator binding."""

from sqlmodel import Session, select

from app.modules.esop.infrastructure.models import ChannelAdmin


def menu_permission_visible(session: Session, user_id, permission_code: str) -> bool:
    if permission_code != "esop:channel:portal":
        return True
    return session.exec(
        select(ChannelAdmin.id).where(ChannelAdmin.user_id == user_id).limit(1)
    ).first() is not None


def protected_user_ids(session: Session, user_ids: set) -> set:
    return set(session.exec(select(ChannelAdmin.user_id).where(ChannelAdmin.user_id.in_(user_ids))).all())
