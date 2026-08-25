"""Customer Success Agent — OpenAI Agents SDK definition and runner."""

from __future__ import annotations

import os

from agents import (
    Agent,
    OpenAIChatCompletionsModel,
    Runner,
    set_tracing_disabled,
)

from agent.context import AgentContext
from agent.prompts import SYSTEM_PROMPT
from agent.tools import ALL_TOOLS

_DEFAULT_MODEL = "qwen-plus"

if os.environ.get("AGENTS_TRACING_DISABLED", "true").lower() in {
    "1", "true", "yes", "on",
}:
    set_tracing_disabled(True)

customer_success_agent = Agent[AgentContext](
    name="Customer Success Agent",
    instructions=SYSTEM_PROMPT,
    tools=ALL_TOOLS,
    model=os.environ.get("QWEN_CHAT_MODEL", _DEFAULT_MODEL),
)


async def run_agent(
    context: AgentContext,
    message: str,
) -> str:
    """Run the Customer Success Agent on a single message.

    Parameters
    ----------
    context:
        Shared agent context (DB pool + Qwen-compatible model client).
    message:
        The customer's inbound message text.

    Returns
    -------
    str
        The agent's final textual output.
    """
    runtime_agent = Agent[AgentContext](
        name=customer_success_agent.name,
        instructions=customer_success_agent.instructions,
        tools=customer_success_agent.tools,
        model=OpenAIChatCompletionsModel(
            model=os.environ.get("QWEN_CHAT_MODEL", _DEFAULT_MODEL),
            openai_client=context.model_client,
        ),
    )
    result = await Runner.run(
        starting_agent=runtime_agent,
        input=message,
        context=context,
    )
    return result.final_output
