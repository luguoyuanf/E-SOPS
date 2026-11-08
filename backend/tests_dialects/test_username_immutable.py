from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app import crud
from app.platform.core.identity_models import User, UserUpdate


@pytest.mark.parametrize('username', ['changed', '', None])
def test_user_update_rejects_username_changes_before_writing(username):
    session = Mock()
    user = User(username='original', hashed_password='unused')
    with pytest.raises(HTTPException) as error:
        crud.update_user(session=session, db_user=user, user_in=UserUpdate(username=username))
    assert error.value.status_code == 422
    assert user.username == 'original'
    session.commit.assert_not_called()


@pytest.mark.parametrize('payload', [{'username': 'original', 'full_name': 'Updated'}, {'full_name': 'Updated'}])
def test_user_update_allows_same_or_omitted_username(payload):
    session = Mock()
    user = User(username='original', hashed_password='unused')
    crud.update_user(session=session, db_user=user, user_in=UserUpdate(**payload))
    assert user.username == 'original'
    assert user.full_name == 'Updated'
    session.commit.assert_called_once()
