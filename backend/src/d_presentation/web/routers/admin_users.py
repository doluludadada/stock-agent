from fastapi import APIRouter, status

from a_domain.model.system.user import User
from a_domain.types.ids import UserId
from d_presentation.web.schemas import UserChangeRequest
from d_presentation.web.session import ManageUsers, NotFound, PrivateAccess, UserPipeline

router = APIRouter(prefix="/admin/users", tags=["Administration"], dependencies=[PrivateAccess, ManageUsers])
"""The administrator's users page. A user who is not an administrator gets 403 and stays signed in."""


@router.get("")
async def list_users(pipeline: UserPipeline) -> list[User]:
    """Every user, oldest first. No administrator sees another user's data: this is the directory only."""
    return await pipeline.load_users()


@router.patch(
    "/{user_id}",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "No such user."},
        status.HTTP_409_CONFLICT: {"description": "No active administrator would remain; nothing saved."},
    },
)
async def change_user(user_id: str, body: UserChangeRequest, pipeline: UserPipeline) -> User:
    """
    Changes a role, deactivates or reactivates a user, or sets a new password. A deactivation or a new password ends
    every session of the user at once; their data stays, and a run of theirs already running finishes.
    """
    user = await pipeline.change_user(UserId(user_id), body.role, body.status, body.password)

    if user is None:
        raise NotFound(f"No user {user_id}.")

    return user
