import secrets

import pytest
from fastapi import HTTPException
from sqlmodel import Session
from test_username_auth import fixture_engine

from app import crud
from app.api.routes.users import create_user
from app.platform.core.identity_models import UserCreate, UserUpdate


def test_email_less_users_can_be_created_updated_and_authenticate():
    with Session(fixture_engine()) as session:
        for username in ['no-email-one', 'no-email-two']:
            password = secrets.token_urlsafe(18)
            user = crud.create_user(session=session, user_create=UserCreate(username=username, password=password))
            assert user.email is None
            assert crud.authenticate(session=session, email=username, password=password).id == user.id
            user = crud.update_user(session=session, db_user=user, user_in=UserUpdate(email='optional@example.com'))
            assert user.email == 'optional@example.com'
            user = crud.update_user(session=session, db_user=user, user_in=UserUpdate(email=None))
            assert user.email is None


@pytest.mark.parametrize('username', [None, '', '   '])
def test_user_management_rejects_missing_username_before_creating(username):
    with pytest.raises(HTTPException) as error:
        create_user(session=None, current_user=None, tenant_context=None,
                    user_in=UserCreate(username=username, password=secrets.token_urlsafe(18)))
    assert error.value.status_code == 422
