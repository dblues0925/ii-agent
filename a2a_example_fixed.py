#!/usr/bin/env python3
"""
A2A Protocol Example: ReviewerAgent and AnthropicFC Agent Communication (Fixed)

This example demonstrates how to wrap existing ii-agent agents (ReviewerAgent and AnthropicFC)
to communicate using the A2A (Agent-to-Agent) protocol.

The A2A protocol enables:
- Standardized agent discovery and capability exchange
- Inter-agent communication with well-defined interfaces
- Maintaining agent opacity while enabling collaboration

Requirements:
    pip install a2a-sdk uvicorn aiohttp
"""
import os
os.environ["PROJECT_ID"] = "backend-alpha-97077"
os.environ["REGION"] = "us-east5"
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/home/pvduy/duy/repos/ii-agent/ii_agent_vertex_ai_service_account.json"
import asyncio
import json
import logging
import os
import sys
import uuid
from typing import Optional, Dict, Any, List
from pathlib import Path
import multiprocessing
import time

# A2A imports
from a2a.types import (
    AgentSkill,
    AgentCard,
    AgentCapabilities,
    Message,
    Task,
)
from a2a.utils import new_agent_text_message
from a2a.server.agent_execution.agent_executor import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.apps.starlette_app import A2AStarletteApplication
from a2a.server.request_handlers.default_request_handler import DefaultRequestHandler
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.server.events.in_memory_queue_manager import InMemoryQueueManager
import uvicorn

# ii-agent imports
from ii_agent.agents.anthropic_fc import AnthropicFC
from ii_agent.agents.reviewer import ReviewerAgent
from ii_agent.llm.context_manager.llm_summarizing import LLMSummarizingContextManager
from ii_agent.llm.token_counter import TokenCounter
from ii_agent.utils.workspace_manager import WorkspaceManager
from ii_agent.tools import get_system_tools
from ii_agent.prompts.system_prompt import SYSTEM_PROMPT
from ii_agent.prompts.reviewer_system_prompt import REVIEWER_SYSTEM_PROMPT
from ii_agent.llm import get_client

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ===== STEP 1: Define Agent Skills =====

# AnthropicFC Agent Skills
general_task_skill = AgentSkill(
    id='general_task',
    name='General Task Execution',
    description='Execute general software engineering tasks, answer questions, and solve problems',
    tags=['general', 'coding', 'problem-solving', 'assistant'],
    examples=[
        'Create a Python script to analyze data',
        'Build a web scraper',
        'Explain how a concept works',
        'Debug this code issue'
    ]
)

# ReviewerAgent Skills  
review_task_skill = AgentSkill(
    id='review_task',
    name='Review Task Execution',
    description='Review the work done by general agent and provide structured feedback',
    tags=['review', 'feedback', 'analysis', 'improvement'],
    examples=[
        'Review the agent execution in workspace X',
        'Analyze the quality of generated code',
        'Provide improvement suggestions'
    ]
)


# ===== STEP 2: Create Agent Cards =====

anthropic_fc_card = AgentCard(
    name='AnthropicFC General Agent',
    description='A general-purpose AI agent that can accomplish tasks and answer questions using various tools',
    url='http://localhost:1212/',
    version='1.0.0',
    defaultInputModes=['text/plain', 'application/json'],
    defaultOutputModes=['text/plain', 'application/json'],
    capabilities=AgentCapabilities(
        streaming=False,
        pushNotifications=False
    ),
    skills=[general_task_skill],
    supportsAuthenticatedExtendedCard=False
)

reviewer_agent_card = AgentCard(
    name='Reviewer Agent',
    description='An agent that reviews and evaluates work done by other agents, providing structured feedback',
    url='http://localhost:1213/',
    version='1.0.0',
    defaultInputModes=['text/plain', 'application/json'],
    defaultOutputModes=['text/plain', 'application/json'],
    capabilities=AgentCapabilities(
        streaming=False,
        pushNotifications=False
    ),
    skills=[review_task_skill],
    supportsAuthenticatedExtendedCard=False
)


# ===== STEP 3: Create Agent Executors =====

class AnthropicFCExecutor(AgentExecutor):
    """A2A Executor wrapper for AnthropicFC Agent"""
    
    def __init__(self):
        self.agent: Optional[AnthropicFC] = None
        self.workspace_manager = WorkspaceManager(root=Path("./workspace"))
        self.session_id = uuid.uuid4()
        
    async def initialize_agent(self):
        """Initialize the AnthropicFC agent"""
        # Initialize LLM client
        client = get_client(
            "anthropic-direct",
            model_name="claude-sonnet-4@20250514",
            use_caching=False,
            project_id=os.getenv("PROJECT_ID", "backend-alpha-97077"),
            region=os.getenv("REGION", "us-east5"),
        )
        message_queue = asyncio.Queue()
        logger_for_agent = logging.getLogger("anthropic_fc_agent")
        
        # Add file handler for anthropic_fc_agent logs
        agent_file_handler = logging.FileHandler('anthropic_fc_agent.log')
        agent_file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        logger_for_agent.addHandler(agent_file_handler)
        logger_for_agent.setLevel(logging.INFO)
        
        # Create context manager
        token_counter = TokenCounter()
        context_manager = LLMSummarizingContextManager(
            client=client,
            token_counter=token_counter,
            logger=logger_for_agent,
            token_budget=100000
        )
        
        # Get all available tools
        tools = get_system_tools(
            client=client,
            workspace_manager=self.workspace_manager,
            message_queue=message_queue,
            container_id=None,
            ask_user_permission=False,
            tool_args={
                "deep_research": False,
                "pdf": False,
                "media_generation": False,
                "audio_generation": False,
                "browser": False,
                "memory_tool": False,
            },
        )
        
        # Create the agent
        self.agent = AnthropicFC(
            system_prompt=SYSTEM_PROMPT,
            client=client,
            tools=tools,
            workspace_manager=self.workspace_manager,
            message_queue=message_queue,
            logger_for_agent_logs=logger_for_agent,
            context_manager=context_manager,
            max_output_tokens_per_turn=32000,
            max_turns=200,
            session_id=self.session_id,
            interactive_mode=False  # Non-interactive for A2A
        )
        
        # Start message processing
        self.agent.start_message_processing()
        
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Execute the AnthropicFC agent via A2A protocol"""
        if not self.agent:
            await self.initialize_agent()
            
        try:
            # Extract the instruction from the request
            # Access the message directly from context
            if hasattr(context.message, 'content'):
                message = context.message.content
            elif hasattr(context.message, 'parts') and context.message.parts:
                # Extract text from the first text part
                first_part = context.message.parts[0]
                if hasattr(first_part, 'text'):
                    message = first_part.text
                elif hasattr(first_part, 'root') and hasattr(first_part.root, 'text'):
                    message = first_part.root.text
                else:
                    message = str(first_part)
            else:
                raise ValueError("No message content found")
            
            # For this demo, we'll assume all requests to this agent are general tasks
            # In a real implementation, you might use message metadata or other means
                
            # Send initial acknowledgment
            event_queue.enqueue_event(
                new_agent_text_message("Starting task execution...")
            )
            
            # Run the agent
            result = self.agent.run_agent(
                instruction=message,
                files=None,
                resume=False
            )
            
            # Send the result
            event_queue.enqueue_event(
                new_agent_text_message(result)
            )
            
            # If workspace was created, include it in metadata
            workspace_path = self.workspace_manager.get_workspace_path()
            if workspace_path:
                event_queue.enqueue_event(
                    Task(
                        id=str(self.session_id),
                        metadata={
                            "workspace_path": str(workspace_path),
                            "session_id": str(self.session_id)
                        }
                    )
                )
                
        except Exception as e:
            logger.error(f"Error in AnthropicFC execution: {str(e)}")
            event_queue.enqueue_event(
                new_agent_text_message(f"Error executing task: {str(e)}")
            )
    
    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Handle cancellation requests"""
        if self.agent:
            self.agent.cancel()
        event_queue.enqueue_event(
            new_agent_text_message("Task cancelled")
        )


class ReviewerAgentExecutor(AgentExecutor):
    """A2A Executor wrapper for ReviewerAgent"""
    
    def __init__(self):
        self.agent: Optional[ReviewerAgent] = None
        self.workspace_manager = WorkspaceManager(root=Path("./workspace"))
        self.session_id = uuid.uuid4()
        
    async def initialize_agent(self):
        """Initialize the ReviewerAgent"""
        # Create necessary components
        client = get_client(
            "anthropic-direct",
            model_name="claude-sonnet-4@20250514",
            use_caching=False,
            project_id=os.getenv("PROJECT_ID", "backend-alpha-97077"),
            region=os.getenv("REGION", "us-east5"),
        )
        message_queue = asyncio.Queue()
        logger_for_agent = logging.getLogger("reviewer_agent")
        
        # Create context manager
        token_counter = TokenCounter()
        context_manager = LLMSummarizingContextManager(
            client=client,
            token_counter=token_counter,
            logger=logger_for_agent,
            token_budget=100000
        )
        
        # Get all available tools
        tools = get_system_tools(
            client=client,
            workspace_manager=self.workspace_manager,
            message_queue=message_queue,
            container_id=None,
            ask_user_permission=False,
        )
        
        # Create the agent
        self.agent = ReviewerAgent(
            system_prompt=REVIEWER_SYSTEM_PROMPT,
            client=client,
            tools=tools,
            workspace_manager=self.workspace_manager,
            message_queue=message_queue,
            logger_for_agent_logs=logger_for_agent,
            context_manager=context_manager,
            max_output_tokens_per_turn=32000,
            max_turns=200,
            session_id=self.session_id,
            interactive_mode=False
        )
        
        # Start message processing
        self.agent.start_message_processing()
        
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Execute the ReviewerAgent via A2A protocol"""
        if not self.agent:
            await self.initialize_agent()
            
        try:
            # Parse the request - expecting JSON with task, workspace_dir, result
            # Access the message directly from context
            if hasattr(context.message, 'content'):
                message = context.message.content
            elif hasattr(context.message, 'parts') and context.message.parts:
                # Extract text from the first text part
                first_part = context.message.parts[0]
                if hasattr(first_part, 'text'):
                    message = first_part.text
                elif hasattr(first_part, 'root') and hasattr(first_part.root, 'text'):
                    message = first_part.root.text
                else:
                    message = str(first_part)
            else:
                raise ValueError("No message content found")
            
            # Try to parse as JSON for structured input
            try:
                review_params = json.loads(message)
                task = review_params.get('task', '')
                workspace_dir = review_params.get('workspace_dir', '')
                result = review_params.get('result', '')
            except json.JSONDecodeError:
                # Fallback to simple text parsing
                event_queue.enqueue_event(
                    new_agent_text_message(
                        "Please provide review parameters as JSON with 'task', 'workspace_dir', and 'result'"
                    )
                )
                return
                
            # Send initial acknowledgment
            event_queue.enqueue_event(
                new_agent_text_message("Starting review process...")
            )
            
            # Run the reviewer agent
            review_result = self.agent.run_agent(
                task=task,
                result=result,
                workspace_dir=workspace_dir,
                resume=False
            )
            
            # Send the review result
            event_queue.enqueue_event(
                new_agent_text_message(review_result)
            )
            
        except Exception as e:
            logger.error(f"Error in ReviewerAgent execution: {str(e)}")
            event_queue.enqueue_event(
                new_agent_text_message(f"Error executing review: {str(e)}")
            )
    
    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Handle cancellation requests"""
        if self.agent:
            self.agent.cancel()
        event_queue.enqueue_event(
            new_agent_text_message("Review cancelled")
        )


# ===== STEP 4: Server Functions =====

async def run_anthropic_fc_server():
    """Run the AnthropicFC agent as an A2A server"""
    executor = AnthropicFCExecutor()
    await executor.initialize_agent()
    
    # Create necessary components
    task_store = InMemoryTaskStore()
    queue_manager = InMemoryQueueManager()
    
    # Create request handler with the executor
    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=task_store,
        queue_manager=queue_manager
    )
    
    # Create the Starlette app using the build() method
    a2a_app = A2AStarletteApplication(
        agent_card=anthropic_fc_card,
        http_handler=handler
    )
    app = a2a_app.build(rpc_url='/rpc')
    
    logger.info("Starting AnthropicFC A2A server on port 1212...")
    config = uvicorn.Config(app, host='0.0.0.0', port=1212, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def run_reviewer_server():
    """Run the ReviewerAgent as an A2A server"""
    executor = ReviewerAgentExecutor()
    await executor.initialize_agent()
    
    # Create necessary components
    task_store = InMemoryTaskStore()
    queue_manager = InMemoryQueueManager()
    
    # Create request handler with the executor
    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=task_store,
        queue_manager=queue_manager
    )
    
    # Create the Starlette app using the build() method
    a2a_app = A2AStarletteApplication(
        agent_card=reviewer_agent_card,
        http_handler=handler
    )
    app = a2a_app.build(rpc_url='/rpc')
    
    logger.info("Starting ReviewerAgent A2A server on port 1213...")
    config = uvicorn.Config(app, host='0.0.0.0', port=1213, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


# ===== STEP 5: Inter-Agent Communication Example =====

async def demonstrate_inter_agent_communication():
    """Demonstrate how agents can communicate via A2A protocol"""
    import aiohttp
    
    logger.info("Starting inter-agent communication demo...")
    
    # Wait for servers to start
    await asyncio.sleep(5)
    
    # Step 1: Send task to AnthropicFC agent
    async with aiohttp.ClientSession() as session:
        # Discover AnthropicFC capabilities
        try:
            async with session.get('http://localhost:1212/.well-known/agent.json') as resp:
                anthropic_fc_info = await resp.json()
                logger.info(f"AnthropicFC capabilities: {json.dumps(anthropic_fc_info, indent=2)}")
        except Exception as e:
            logger.error(f"Failed to get AnthropicFC capabilities: {e}")
            return
        
        # Send a task to AnthropicFC
        task_request = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "params": {
                "message": {
                    "messageId": str(uuid.uuid4()),
                    "role": "user",
                    "parts": [
                        {
                            "type": "text",
                            "text": "Create a simple Python function to calculate fibonacci numbers"
                        }
                    ]
                },
                "skill_id": "general_task"
            },
            "id": 1
        }
        
        logger.info("Sending task to AnthropicFC agent...")
        try:
            async with session.post(
                'http://localhost:1212/rpc',
                json=task_request,
                headers={'Content-Type': 'application/json'}
            ) as resp:
                result = await resp.json()
                logger.info(f"AnthropicFC result: {json.dumps(result, indent=2)}")
                import ipdb; ipdb.set_trace()
                # Extract workspace path from result if available
                workspace_path = None
                if 'result' in result and 'metadata' in result['result']:
                    workspace_path = result['result']['metadata'].get('workspace_path')
        except Exception as e:
            logger.error(f"Failed to send task to AnthropicFC: {e}")
            return
        
        # Step 2: Send review request to ReviewerAgent
        if workspace_path:
            review_request = {
                "jsonrpc": "2.0",
                "method": "message/send",
                "params": {
                    "message": {
                        "messageId": str(uuid.uuid4()),
                        "role": "user",
                        "parts": [
                            {
                                "type": "text",
                                "text": json.dumps({
                                    "task": "Create a simple Python function to calculate fibonacci numbers",
                                    "workspace_dir": workspace_path,
                                    "result": "Task completed successfully"
                                })
                            }
                        ]
                    },
                    "skill_id": "review_task"
                },
                "id": 2
            }
            
            logger.info("Sending review request to ReviewerAgent...")
            try:
                async with session.post(
                    'http://localhost:1213/rpc',
                    json=review_request,
                    headers={'Content-Type': 'application/json'}
                ) as resp:
                    review_result = await resp.json()
                    logger.info(f"ReviewerAgent result: {json.dumps(review_result, indent=2)}")
            except Exception as e:
                logger.error(f"Failed to send review request: {e}")


# ===== STEP 6: Process-based Server Runners =====

def start_anthropic_fc_server():
    """Start AnthropicFC server in a separate process"""
    asyncio.run(run_anthropic_fc_server())


def start_reviewer_server():
    """Start Reviewer server in a separate process"""
    asyncio.run(run_reviewer_server())


# ===== STEP 7: Main Entry Point =====

def main():
    """Main entry point - runs both servers in separate processes and demonstrates communication"""
    
    # Start both servers in separate processes
    logger.info("Starting A2A servers in separate processes...")
    
    anthropic_process = multiprocessing.Process(target=start_anthropic_fc_server)
    reviewer_process = multiprocessing.Process(target=start_reviewer_server)
    
    anthropic_process.start()
    reviewer_process.start()
    # Run the demonstration in the main process
    try:
        asyncio.run(demonstrate_inter_agent_communication())
        
        logger.info("\nServers are running. Press Ctrl+C to stop.")
        
        # Keep the main process running
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("\nShutting down servers...")
        anthropic_process.terminate()
        reviewer_process.terminate()
        anthropic_process.join()
        reviewer_process.join()
        logger.info("Servers stopped.")


if __name__ == "__main__":
    # Run the example
    # Usage:
    # 1. Set ANTHROPIC_API_KEY environment variable
    # 2. Run: python a2a_example_fixed.py
    # 3. The script will start both agents as A2A servers and demonstrate communication
    
    main()
