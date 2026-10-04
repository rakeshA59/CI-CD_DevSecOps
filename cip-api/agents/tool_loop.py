"""
Tool loop – the agent ⇄ ToolNode cycle of the sdlc-api graphs, as one reusable coroutine.

The LLM gets the tools (`bind_tools`), decides which to call, sees each result and continues until it answers
without a tool call (or max_steps is reached). Every tool call is streamed to the UI.
"""

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from services.stream_event_writer import StreamStatus
from utils.agent_events import emit


async def tool_loop(llm, tools: list, system: str, human: str, task_id: str = "", node: str = "",
                    max_steps: int = 12) -> str:
    """Run the agent with its tools; returns the final answer text."""
    by_name = {t.name: t for t in tools}
    messages = [SystemMessage(content=system), HumanMessage(content=human)]
    agent = llm.bind_tools(tools)
    for _ in range(max_steps):
        reply = await agent.ainvoke(messages)
        messages.append(reply)
        if not getattr(reply, "tool_calls", None):
            return reply.content if isinstance(reply.content, str) else json.dumps(reply.content)
        for call in reply.tool_calls:
            args = call.get("args") or {}
            if task_id:
                await emit(task_id, node, StreamStatus.PROGRESS, f"🔧 {call['name']}({', '.join(f'{k}={str(v)[:60]}' for k, v in args.items())})")
            try:
                result = await by_name[call["name"]].ainvoke(args)
            except Exception as e:  # noqa: BLE001
                logging.warning("[%s] tool %s failed: %s", node, call["name"], e)
                result = f"tool error: {e}"
            messages.append(ToolMessage(content=str(result)[:12000], tool_call_id=call["id"]))
    return "stopped after the maximum number of tool calls"
