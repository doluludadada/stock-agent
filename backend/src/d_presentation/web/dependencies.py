from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from d_presentation.dependencies import Runtime
from d_presentation.web.workflow_runs import WorkflowRuns

bearer = HTTPBearer(auto_error=False, description="The value of API_TOKEN. Reads need no token.")


def get_runtime(request: Request) -> Runtime:
    """The runtime the app's lifespan built once at startup."""
    return request.app.state.runtime


def get_workflow_runs(request: Request) -> WorkflowRuns:
    return request.app.state.workflow_runs


RuntimeDependency = Annotated[Runtime, Depends(get_runtime)]
WorkflowRunsDependency = Annotated[WorkflowRuns, Depends(get_workflow_runs)]


def require_write_permission(
    runtime: RuntimeDependency, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> None:
    """Every write: 403 while API_TOKEN is unset, 401 without its bearer token. The body's `confirm: true` is checked after."""
    token = runtime.config.api.token

    if token is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Writes are disabled. Set API_TOKEN to enable them.")

    if credentials is None or not compare_digest(credentials.credentials.encode(), token.get_secret_value().encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "A valid bearer token is required.", headers={"WWW-Authenticate": "Bearer"})


WritePermission = Depends(require_write_permission)
