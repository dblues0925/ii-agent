import asyncio
import json
import logging
from typing import Any, List, Optional
import uuid
from datetime import datetime

from fastapi import WebSocket
from ii_agent.agents.base import BaseAgent
from ii_agent.core.event import EventType, RealtimeEvent
from ii_agent.llm.base import LLMClient, TextResult, ToolCallParameters
from ii_agent.llm.context_manager.base import ContextManager
from ii_agent.llm.message_history import MessageHistory
from ii_agent.tools.base import ToolImplOutput, LLMTool
from ii_agent.db.manager import DatabaseManager
from ii_agent.tools import AgentToolManager
from ii_agent.utils.workspace_manager import WorkspaceManager


class ReviewerAgent(BaseAgent):
    name = "reviewer_agent"
    description = """\
A comprehensive reviewer agent that evaluates and reviews the results/websites/slides created by general agent, 
then provides detailed feedback and improvement suggestions with special focus on functionality testing.

This agent conducts thorough reviews with emphasis on:
- Testing ALL interactive elements (buttons, forms, navigation, etc.)
- Verifying website functionality and user experience
- Providing detailed, natural language feedback without format restrictions
- Identifying specific issues and areas for improvement
"""
    input_schema = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "The task that the general agent is trying to solve"
            },
            "workspace_dir": {
                "type": "string",
                "description": "The workspace directory of the general agent execution to review"
            },
        },
        "required": ["task", "workspace_dir"]
    }
    websocket: Optional[WebSocket]

    def __init__(
        self,
        system_prompt: str,
        client: LLMClient,
        tools: List[LLMTool],
        workspace_manager: WorkspaceManager,
        message_queue: asyncio.Queue,
        logger_for_agent_logs: logging.Logger,
        context_manager: ContextManager,
        max_output_tokens_per_turn: int = 8192,
        max_turns: int = 10,
        websocket: Optional[WebSocket] = None,
        session_id: Optional[uuid.UUID] = None,
        interactive_mode: bool = True,
    ):
        """Initialize the reviewer agent."""
        super().__init__()
        self.workspace_manager = workspace_manager
        self.system_prompt = system_prompt
        self.client = client
        self.tool_manager = AgentToolManager(
            tools=tools,
            logger_for_agent_logs=logger_for_agent_logs,
            interactive_mode=interactive_mode,
        )

        self.logger_for_agent_logs = logger_for_agent_logs
        self.max_output_tokens = max_output_tokens_per_turn
        self.max_turns = max_turns

        self.interrupted = False
        self.history = MessageHistory(context_manager)
        self.context_manager = context_manager
        self.session_id = session_id

        # Initialize database manager
        self.db_manager = DatabaseManager()

        self.message_queue = message_queue
        self.websocket = websocket

    async def _process_messages(self):
        try:
            while True:
                try:
                    message: RealtimeEvent = await self.message_queue.get()

                    # Save all events to database if we have a session
                    if self.session_id is not None:
                        self.db_manager.save_event(self.session_id, message)
                    else:
                        self.logger_for_agent_logs.info(
                            f"No session ID, skipping event: {message}"
                        )

                    # Only send to websocket if this is not an event from the client and websocket exists
                    if (
                        message.type != EventType.USER_MESSAGE
                        and self.websocket is not None
                    ):
                        try:
                            await self.websocket.send_json(message.model_dump())
                        except Exception as e:
                            # If websocket send fails, just log it and continue processing
                            self.logger_for_agent_logs.warning(
                                f"Failed to send message to websocket: {str(e)}"
                            )
                            # Set websocket to None to prevent further attempts
                            self.websocket = None

                    self.message_queue.task_done()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    self.logger_for_agent_logs.error(
                        f"Error processing WebSocket message: {str(e)}"
                    )
        except asyncio.CancelledError:
            self.logger_for_agent_logs.info("Message processor stopped")
        except Exception as e:
            self.logger_for_agent_logs.error(f"Error in message processor: {str(e)}")

    def _validate_tool_parameters(self):
        """Validate tool parameters and check for duplicates."""
        tool_params = [tool.get_tool_param() for tool in self.tool_manager.get_tools()]
        tool_names = [param.name for param in tool_params]
        sorted_names = sorted(tool_names)
        for i in range(len(sorted_names) - 1):
            if sorted_names[i] == sorted_names[i + 1]:
                raise ValueError(f"Tool {sorted_names[i]} is duplicated")
        return tool_params

    def start_message_processing(self):
        """Start processing the message queue."""
        return asyncio.create_task(self._process_messages())

    def run_impl(
        self,
        tool_input: dict[str, Any],
        message_history: Optional[MessageHistory] = None,
    ) -> ToolImplOutput:
        task = tool_input["task"]
        workspace_dir = tool_input["workspace_dir"]
        result = tool_input["result"]
        user_input_delimiter = "-" * 45 + " REVIEWER INPUT " + "-" * 45
        self.logger_for_agent_logs.info(f"\n{user_input_delimiter}\nReviewing agent logs and output...\n")

        # Construct the review instruction
        review_instruction = f"""You are a reviewer agent tasked with evaluating the work done by an general agent. 
You have access to all the same tools that the general agent has.

Here is the task that the general agent is trying to solve:
{task}

Here is the result of the general agent's execution:
{result}

Here is the workspace directory of the general agent's execution:
{workspace_dir}

Now your turn to review the general agent's work.
"""

        review_instruction_ = """
Your task is to conduct a comprehensive review following these steps:

1. **Context Analysis**: Understand the task complexity, user expectations, and success criteria
2. **Result Examination**: Check the final result of the general agent's execution (websites, slide decks, documents, etc.)
   - **PRIORITY**: Use browser tools to thoroughly test websites - click ALL buttons, fill ALL forms, test ALL interactive elements
   - Test navigation, responsiveness, and user experience
   - Read slide deck files and evaluate structure/content
   - Examine any generated documents or code
3. **Workspace Analysis**: Analyze the workspace directory to understand the agent's approach
   - Only check inside this workspace directory, do not check outside of it
   - Check todo file if it exists to understand the pipeline used
   - Review logs and execution traces for insights
4. **Quality Assessment**: Evaluate against structured criteria (completeness, accuracy, efficiency, user experience)
5. **Improvement Identification**: Identify areas where agent capabilities could be enhanced
6. **Actionable Recommendations**: Generate detailed feedback with prioritized improvements

Provide your comprehensive review in natural language format. You have complete freedom to structure your response as you see fit. Focus on being thorough, specific, and honest about what works and what doesn't work. Pay special attention to functionality testing and user experience."""

        self.history.add_user_prompt(review_instruction)
        self.interrupted = False

        remaining_turns = self.max_turns
        while remaining_turns > 0:
            remaining_turns -= 1

            delimiter = "-" * 45 + " REVIEWER TURN " + "-" * 45
            self.logger_for_agent_logs.info(f"\n{delimiter}\n")

            # Get tool parameters for available tools
            all_tool_params = self._validate_tool_parameters()

            if self.interrupted:
                return ToolImplOutput(
                    tool_output="Reviewer interrupted",
                    tool_result_message="Reviewer interrupted by user"
                )

            current_messages = self.history.get_messages_for_llm()
            current_tok_count = self.context_manager.count_tokens(current_messages)
            self.logger_for_agent_logs.info(
                f"(Current token count: {current_tok_count})\n"
            )

            truncated_messages_for_llm = (
                self.context_manager.apply_truncation_if_needed(current_messages)
            )

            self.history.set_message_list(truncated_messages_for_llm)

            model_response, _ = self.client.generate(
                messages=truncated_messages_for_llm,
                max_tokens=self.max_output_tokens,
                tools=all_tool_params,
                system_prompt=self.system_prompt,
            )

            if len(model_response) == 0:
                model_response = [TextResult(text="No response from model")]

            # Add the raw response to the canonical history
            self.history.add_assistant_turn(model_response)

            # Handle tool calls
            pending_tool_calls = self.history.get_pending_tool_calls()

            if len(pending_tool_calls) > 1:
                raise ValueError("Only one tool call per turn is supported")

            if len(pending_tool_calls) == 1:
                tool_call = pending_tool_calls[0]

                self.message_queue.put_nowait(
                    RealtimeEvent(
                        type=EventType.TOOL_CALL,
                        content={
                            "tool_call_id": tool_call.tool_call_id,
                            "tool_name": tool_call.tool_name,
                            "tool_input": tool_call.tool_input,
                        },
                    )
                )

                text_results = [
                    item for item in model_response if isinstance(item, TextResult)
                ]
                if len(text_results) > 0:
                    text_result = text_results[0]
                    self.logger_for_agent_logs.info(
                        f"Reviewer planning next step: {text_result.text}\n",
                    )

                # Handle tool call by the reviewer
                if self.interrupted:
                    self.add_tool_call_result(tool_call, "Tool execution interrupted")
                    return ToolImplOutput(
                        tool_output="Reviewer interrupted",
                        tool_result_message="Reviewer interrupted during tool execution"
                    )
                
                tool_result = self.tool_manager.run_tool(tool_call, self.history)
                self.add_tool_call_result(tool_call, tool_result)
                if tool_call.tool_name == "return_control_to_user":
                    # Send the review message to the message queue for websocket transmission
                    if self.websocket:
                        review_message = RealtimeEvent(
                            type=EventType.AGENT_RESPONSE,
                            content={
                                "agent_name": self.name,
                                "content": tool_result,
                                "timestamp": datetime.now().isoformat()
                            }
                        )
                        # Put the message in the queue instead of using await
                        self.message_queue.put_nowait(review_message)
                    
                    return ToolImplOutput(
                        tool_output=tool_result,
                        tool_result_message="Reviewer completed comprehensive review"
                    )

        # If we exhausted all turns without completing review
        return ToolImplOutput(
            tool_output="ERROR: Reviewer did not complete review within maximum turns. The review process was interrupted or took too long to complete.",
            tool_result_message="Review incomplete - maximum turns reached"
        )

    def get_tool_start_message(self, tool_input: dict[str, Any]) -> str:
        return f"Reviewer started to analyze agent logs"

    def add_tool_call_result(self, tool_call: ToolCallParameters, tool_result: str):
        """Add a tool call result to the history and send it to the message queue."""
        self.history.add_tool_call_result(tool_call, tool_result)

        self.message_queue.put_nowait(
            RealtimeEvent(
                type=EventType.TOOL_RESULT,
                content={
                    "tool_call_id": tool_call.tool_call_id,
                    "tool_name": tool_call.tool_name,
                    "result": tool_result,
                },
            )
        )

    def cancel(self):
        """Cancel the reviewer execution."""
        self.interrupted = True
        self.logger_for_agent_logs.info("Reviewer cancellation requested")

    def run_agent(
        self,
        task: str,
        result: str,
        workspace_dir: str,
        resume: bool = False,
    ) -> str:
        """Start a new reviewer run.

        Args:
            workspace_dir: The workspace directory to review.
            resume: Whether to resume the reviewer from the previous state,
                continuing the dialog.

        Returns:
            The review result string.
        """
        self.tool_manager.reset()
        if resume:
            assert self.history.is_next_turn_user()
        else:
            self.history.clear()
            self.interrupted = False

        tool_input = {
            "task": task,
            "workspace_dir": workspace_dir,
            "result": result,
        }
        return self.run(tool_input, self.history)

    def clear(self):
        """Clear the dialog and reset interruption state."""
        self.history.clear()
        self.interrupted = False