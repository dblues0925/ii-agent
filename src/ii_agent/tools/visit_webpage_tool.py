from ii_agent.tools.base import (
    LLMTool,
    ToolImplOutput,
)
from typing import Any, Optional
from ii_agent.llm.message_history import MessageHistory
from ii_agent.tools.visit_webpage_client import (
    create_visit_client,
    WebpageVisitException,
    ContentExtractionError,
    NetworkError,
)
from ii_agent.utils.constants import VISIT_WEB_PAGE_MAX_OUTPUT_LENGTH


class VisitWebpageTool(LLMTool):
    name = "visit_webpage"
    description = "You should call this tool when you need to visit a webpage and extract its content. Returns webpage content as text."
    input_schema = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The url of the webpage to visit.",
            }
        },
        "required": ["url"],
    }
    output_type = "string"

    def __init__(self, max_output_length: int = VISIT_WEB_PAGE_MAX_OUTPUT_LENGTH):
        self.max_output_length = max_output_length
        self.visit_client = create_visit_client(max_output_length=max_output_length)

    async def run_impl(
        self,
        tool_input: dict[str, Any],
        message_history: Optional[MessageHistory] = None,
    ) -> ToolImplOutput:
        url = tool_input["url"]
        if "arxiv.org/abs" in url:
            url = "https://arxiv.org/html/" + url.split("/")[-1]

        try:
            content = await self.visit_client.forward_async(url)
            return ToolImplOutput(
                content,
                f"Successfully visited {url}",
                auxiliary_data={"success": True, "url": url},
            )
        except Exception as e:
            error_message = f"Error visiting {url}: {str(e)}"
            return ToolImplOutput(
                error_message,
                f"Failed to visit {url}",
                auxiliary_data={"success": False, "url": url, "error": str(e)},
            )
