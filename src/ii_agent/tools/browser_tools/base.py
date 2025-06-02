import asyncio

from typing import Any, Optional
from ii_agent.tools.base import (
    LLMTool,
    ToolImplOutput,
)
from ii_agent.browser.browser import Browser
from ii_agent.llm.message_history import MessageHistory


def get_event_loop():
    try:
        # Try to get the existing event loop
        loop = asyncio.get_event_loop()
    except RuntimeError:
        # If no event loop exists, create a new one
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


class BrowserTool(LLMTool):
    def __init__(self, browser: Browser):
        self.browser = browser

    async def _run(
        self,
        tool_input: dict[str, Any],
        message_history: Optional[MessageHistory] = None,
    ) -> ToolImplOutput:
        raise NotImplementedError("Subclasses must implement this method")

    def run_impl(
        self,
        tool_input: dict[str, Any],
        message_history: Optional[MessageHistory] = None,
    ) -> ToolImplOutput:
        try:
            # Check if we're already in an async context
            loop = asyncio.get_running_loop()
            # If we're in an async context, we can't use run_until_complete
            # Instead, we need to handle this differently
            import concurrent.futures
            import threading
            
            # Create a new event loop in a separate thread
            def run_in_new_loop():
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    return new_loop.run_until_complete(self._run(tool_input, message_history))
                finally:
                    new_loop.close()
            
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_in_new_loop)
                return future.result()
                
        except RuntimeError:
            # No running loop, safe to use run_until_complete
            loop = get_event_loop()
            return loop.run_until_complete(self._run(tool_input, message_history))
