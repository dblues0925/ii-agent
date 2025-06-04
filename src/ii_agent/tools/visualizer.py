import mimetypes
from typing import Any, Optional
import base64
from pathlib import Path

from ii_agent.tools.base import (
    LLMTool,
    ToolImplOutput,
)
from ii_agent.llm.message_history import MessageHistory
from .utils import encode_image
from ii_agent.utils import WorkspaceManager


class DisplayImageTool(LLMTool):
    name = "display_image"
    description = "A tool that loads and displays images."
    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "The path to the image to load. This should be a local path to downloaded image.",
            },
        },
        "required": ["file_path"],
    }

    def __init__(self, workspace_manager: WorkspaceManager):
        self.workspace_manager = workspace_manager

    async def run_impl(
        self,
        tool_input: dict[str, Any],
        message_history: Optional[MessageHistory] = None,
    ) -> ToolImplOutput:
        file_path = tool_input["file_path"]
        
        # Ensure the path is treated as relative to the workspace root
        full_file_path = self.workspace_manager.workspace_path(Path(file_path))
        
        if not full_file_path.exists():
            return ToolImplOutput(
                f"Error: File not found at {file_path}",
                f"File not found at {file_path}",
                {"success": False, "error": "File not found"},
            )
        if not full_file_path.is_file():
            return ToolImplOutput(
                f"Error: Path {file_path} is not a file.",
                f"Path {file_path} is not a file.",
                {"success": False, "error": "Path is not a file"},
            )
        
        # Check if the file is an image
        allowed_extensions = ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg']
        if full_file_path.suffix.lower() not in allowed_extensions:
            return ToolImplOutput(
                f"Error: File {file_path} is not a supported image format. Supported formats: {', '.join(allowed_extensions)}",
                f"File {file_path} is not a supported image format",
                {"success": False, "error": "Unsupported image format"},
            )
        
        try:
            # Read and encode the image
            with open(full_file_path, "rb") as image_file:
                encoded_image = base64.b64encode(image_file.read()).decode('utf-8')
            
            # Determine the media type
            media_type_map = {
                '.png': 'image/png',
                '.jpg': 'image/jpeg', 
                '.jpeg': 'image/jpeg',
                '.gif': 'image/gif',
                '.bmp': 'image/bmp',
                '.webp': 'image/webp',
                '.svg': 'image/svg+xml'
            }
            media_type = media_type_map.get(full_file_path.suffix.lower(), 'image/png')
            
            # Return the image as a message content block
            image_content = {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": encoded_image
                }
            }
            
            return ToolImplOutput(
                [image_content],
                f"Successfully displayed image {file_path}",
                {"success": True, "media_type": media_type},
            )
            
        except Exception as e:
            return ToolImplOutput(
                f"Error reading image {file_path}: {str(e)}",
                f"Failed to display image {file_path}",
                {"success": False, "error": str(e)},
            )
