import asyncio
import json
import logging
from typing import Any, List, Optional
import uuid

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
A reviewer agent that evaluates and reviews the results/websites/slides created by general agent, 
then suggests improvements for the general agent to make better results.

This agent has access to all tools that general agent has access to and returns a structured JSON response with:
- summarization: Analysis of how the agent tried to solve the task
- potential_improvements: Identified improvements to enhance agent capabilities  
- improvement_proposal: One high-impact improvement described in detail
- implementation_suggestion: Critical suggestions for implementation
- problem_description: Task description for implementation
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
        self.history = MessageHistory()
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

        user_input_delimiter = "-" * 45 + " REVIEWER INPUT " + "-" * 45
        self.logger_for_agent_logs.info(f"\n{user_input_delimiter}\nReviewing agent logs and output...\n")

        # Construct the review instruction
        review_instruction = f"""You are a reviewer agent tasked with evaluating the work done by an general agent. 
You have access to all the same tools that the general agent has.

Here is the task that the general agent is trying to solve:
{task}

Here is the workspace directory of the general agent's execution:
{workspace_dir}

"""

        review_instruction += """
Your task is to:
1. Analyze the workspace directory to understand how the agent tried to solve the task, only check inside this workspace directory, do not check outside of it
2. Check todo file if it exists, if it does, then you can read file to understand the pipeline of the general agent used to solve the task
3. Deep dive into other files in the workspace directory to understand the general agent's capabilities and how it tried to solve the task
4. Analyze and provide feedback to the general agent on how it can improve its capabilities
5. Generate a structured JSON response

You must respond precisely in the following format including the JSON start and end markers:
```json
{
    "summarization": "Analyze the logs and summarize how the agent tried to solve the task, noting which tools were used and any issues encountered",
    "potential_improvements": "Identify potential improvements to enhance the agent's general capabilities (not task-specific fixes)",
    "improvement_proposal": "Choose ONE high-impact improvement and describe it in detail as a comprehensive enhancement plan",
    "implementation_suggestion": "Describe what feature or tool could be added/modified to implement the proposed improvement",
    "problem_description": "Phrase the improvement proposal as a clear task description for a software engineer to implement"
}
```"""

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

            if len(pending_tool_calls) == 0:
                # No tools were called, check if we have a JSON response
                last_response = self.history.get_last_assistant_text_response()
                
                if last_response:
                    # Try to extract JSON from the response
                    try:
                        # Look for JSON between ```json and ``` markers
                        if "```json" in last_response and "```" in last_response:
                            json_start = last_response.find("```json") + 7
                            json_end = last_response.find("```", json_start)
                            json_str = last_response[json_start:json_end].strip()
                            
                            # Parse to validate JSON
                            json.loads(json_str)
                            
                            self.logger_for_agent_logs.info("Reviewer completed with JSON response")
                            return ToolImplOutput(
                                tool_output=json_str,
                                tool_result_message="Review completed successfully"
                            )
                    except Exception as e:
                        self.logger_for_agent_logs.warning(f"Failed to parse JSON response: {e}")
                
                # If no response, JSON parsing failed, or no tools were called, prompt for JSON
                reminder = "Please provide your review in the exact JSON format specified in the instructions, including the ```json and ``` markers."
                self.history.add_user_prompt(reminder)
                continue

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
                    return ToolImplOutput(
                        tool_output=tool_result,
                        tool_result_message="Reviewer completed with JSON response"
                    )

        # If we exhausted all turns without producing JSON
        return ToolImplOutput(
            tool_output='{"error": "Reviewer did not complete review within maximum turns"}',
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
        }
        return self.run(tool_input, self.history)

    def clear(self):
        """Clear the dialog and reset interruption state."""
        self.history.clear()
        self.interrupted = False