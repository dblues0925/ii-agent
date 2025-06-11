from pathlib import Path
from typing import Optional


class WorkspaceManager:
    root: Path

    def __init__(self, root: Path, container_workspace: Optional[Path] = None):
        self.root = root.absolute()
        self.container_workspace = container_workspace

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
            if self.container_workspace:
                return self.container_workspace / path
            else:
                return self.root / path
        return path

    def root_path(self) -> Path:
        """Return the absolute path of the workspace root.
        If there is no container workspace, return the absolute local path.
        """
        if self.container_workspace:
            return self.container_workspace.absolute()
        else:
            return self.root.absolute()

    def relative_path(self, path: Path | str) -> Path:
        """Given a path, return the relative path from the workspace root.
        If the path is not under the workspace root, returns the absolute path.
        """
        path = Path(path)
        if self.container_workspace:
            abs_path = self.container_path(path)
        else:
            abs_path = self.workspace_path(path)
        try:
            if not self.container_workspace:
                return abs_path.relative_to(self.root.absolute())
            else:
                return abs_path
        except ValueError:
            return abs_path
