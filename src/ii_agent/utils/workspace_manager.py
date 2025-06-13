from enum import Enum
import os
from pathlib import Path
import uuid

from e2b import Sandbox

from ii_agent.sandbox.config import SandboxSettings
from ii_agent.sandbox.docker_sandbox import DockerSandbox


class WorkSpaceMode(Enum):
    DOCKER = "docker"
    E2B = "e2b"
    LOCAL = None


class WorkspaceManager:
    root: Path
    session_id: str
    workspace_mode: WorkSpaceMode

    def __init__(
        self, workspace_root: str, workspace_mode: WorkSpaceMode = WorkSpaceMode.LOCAL
    ):
        self.workspace_root = workspace_root
        self.workspace_mode = workspace_mode

    async def init(self):
        (
            self.root,
            self.container_workspace,
            self.session_id,
        ) = await self._init_workspace(self.workspace_root, self.deploy_mode)

    def _is_local_workspace(self) -> bool:
        return self.deploy_mode == WorkSpaceMode.LOCAL

    def use_container_workspace(self) -> bool:
        return self.deploy_mode != WorkSpaceMode.LOCAL

    def workspace_path(self, path: Path | str) -> Path:
        """Given a path, possibly in a container workspace, return the absolute local path."""
        path = Path(path)
        if not path.is_absolute():
            return self.root / path
        if self.container_workspace and path.is_relative_to(self.container_workspace):
            return self.root / path.relative_to(self.container_workspace)
        return path

    def container_path(self, path: Path | str) -> Path:
        """Given a path, possibly in the local workspace, return the absolute container path.
        If there is no container workspace, return the absolute local path.
        """
        path = Path(path)
        if not path.is_absolute():
            if not self._is_local_workspace():
                return self.container_workspace / path
            else:
                return self.root / path
        return path

    def root_path(self) -> Path:
        """Return the absolute path of the workspace root.
        If there is no container workspace, return the absolute local path.
        """
        if not self._is_local_workspace():
            return self.container_workspace.absolute()
        else:
            return self.root.absolute()

    def relative_path(self, path: Path | str) -> Path:
        """Given a path, return the relative path from the workspace root.
        If the path is not under the workspace root, returns the absolute path.
        """
        path = Path(path)
        if not self._is_local_workspace():
            abs_path = self.container_path(path)
        else:
            abs_path = self.workspace_path(path)
        try:
            if self._is_local_workspace():
                return abs_path.relative_to(self.root.absolute())
            else:
                return abs_path
        except ValueError:
            return abs_path

    async def _init_workspace(
        self, workspace_root: str, deploy_mode: WorkSpaceMode = WorkSpaceMode.LOCAL
    ):
        """Create a new workspace manager instance for a websocket connection."""
        session_id, container_path = await self._create_workspace(deploy_mode)
        workspace_path = Path(workspace_root).resolve()
        session_workspace = workspace_path / session_id
        session_workspace.mkdir(parents=True, exist_ok=True)

        return session_workspace, container_path, session_id

    async def _create_workspace(self, deploy_mode: WorkSpaceMode = WorkSpaceMode.LOCAL):
        sandbox_settings = SandboxSettings()
        if deploy_mode == WorkSpaceMode.E2B:
            sandbox = Sandbox(os.getenv("E2B_TEMPLATE_ID"), timeout=3600)
            session_id = sandbox.sandbox_id
            container_path = Path(sandbox_settings.work_dir)
        elif deploy_mode == WorkSpaceMode.DOCKER:
            session_id = str(uuid.uuid4())
            await self._create_container_workspace(container_name=session_id)
            container_path = Path(sandbox_settings.work_dir)
        else:
            session_id = str(uuid.uuid4())
            container_path = None
        return session_id, container_path

    async def _create_container_workspace(self, container_name: str):
        settings = SandboxSettings()
        await DockerSandbox(
            container_name=container_name,
            config=settings,
            volume_bindings={
                os.getenv("WORKSPACE_PATH") + "/" + container_name: settings.work_dir
            },
        ).create()
