from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import json
import re
from typing import Any
import uuid

from src.utils.llm import LLMClientFactory


@dataclass
class DemoAgentResponse:
    """Response payload for demo agent interactions."""
    conversation_id: str
    user_message: str
    assistant_message: str
    tool_call: dict[str, Any] | None


class DemoAgent:
    """Tiny agent used for demo conversation generation.

    This is intentionally minimal: it uses a prompt artifact and emits a
    single tool call with a mocked result for the demo flow.
    """

    def __init__(self, prompt_path: str | Path = "artifacts/prompts/prompt_v1.txt"):
        self.prompt_path = Path(prompt_path)
        self.factory = LLMClientFactory()

    def generate(
        self,
        user_message: str,
        force_error: bool = False,
        conversation_id: str | None = None,
    ) -> DemoAgentResponse:
        """Generate a one-turn assistant response with a tool call."""
        prompt = self._load_prompt()
        assistant_message, tool_call = self._call_llm_with_tools(
            prompt,
            user_message,
            force_error=force_error,
        )

        return DemoAgentResponse(
            conversation_id=conversation_id or f"demo_{uuid.uuid4()}",
            user_message=user_message,
            assistant_message=assistant_message,
            tool_call=tool_call,
        )

    def generate_turn(
        self,
        user_message: str,
        force_error: bool = False,
    ) -> tuple[str, dict[str, Any] | None]:
        """Generate assistant content and a tool call for an existing conversation."""
        prompt = self._load_prompt()
        assistant_message, tool_call = self._call_llm_with_tools(
            prompt,
            user_message,
            force_error=force_error,
        )
        return assistant_message, tool_call

    def _load_prompt(self) -> str:
        """Load the current prompt artifact."""
        active_prompt = Path("artifacts/prompts/active_prompt.txt")
        if active_prompt.exists():
            self.prompt_path = active_prompt
            return active_prompt.read_text()
        if self.prompt_path.exists():
            return self.prompt_path.read_text()
        return "You are a helpful travel assistant."

    def _call_llm_with_tools(
        self,
        prompt: str,
        user_message: str,
        force_error: bool = False,
    ) -> tuple[str, dict[str, Any] | None]:
        """Call the LLM with tool definitions and return response + tool call."""
        client = self.factory.get_client()
        if not client.api_key:
            return "Mock response: I can help with that. Let me check options.", None

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "flight_search",
                    "description": "Search for flights by destination and date.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "destination": {"type": "string"},
                            "date": {"type": "string"},
                            "origin": {"type": "string"},
                            "passengers": {"type": "integer"},
                            "class": {"type": "string"},
                        },
                        "required": ["destination", "date"],
                    },
                },
            }
        ]

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_message},
        ]
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.2,
        )

        choice = response.choices[0].message
        tool_calls = choice.tool_calls or []
        if not tool_calls:
            return choice.content or "", None

        tool_call = tool_calls[0]
        tool_args = json.loads(tool_call.function.arguments or "{}")
        if force_error and "date" in tool_args:
            tool_args["date"] = "2024/01/22"

        tool_result = self._run_tool(tool_call.function.name, tool_args)
        messages.append({
            "role": "assistant",
            "content": choice.content or "",
            "tool_calls": tool_calls,
        })
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "name": tool_call.function.name,
            "content": json.dumps(tool_result),
        })

        followup = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.2,
        )
        assistant_message = followup.choices[0].message.content or ""

        return assistant_message, {
            "tool_name": tool_call.function.name,
            "parameters": tool_args,
            "result": tool_result,
            "execution_time_ms": 120,
        }

    def _run_tool(self, tool_name: str, parameters: dict[str, Any]) -> dict[str, Any]:
        """Return a mocked tool result for the demo."""
        if tool_name == "flight_search":
            date_value = str(parameters.get("date", ""))
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_value):
                return {
                    "status": "error",
                    "error": f"Invalid date format: {date_value}. Expected YYYY-MM-DD.",
                    "params": parameters,
                }
            return {
                "status": "success",
                "flights": ["F123", "F456"],
                "params": parameters,
            }
        return {"status": "error", "message": f"Unknown tool: {tool_name}"}

    def _extract_destination(self, text: str) -> str | None:
        """Best-effort extraction of a destination city."""
        match = re.search(r"to ([A-Za-z ]+)", text)
        if not match:
            return None
        return match.group(1).strip().title()


def build_conversation_payload(response: DemoAgentResponse, prompt_path: Path) -> dict[str, Any]:
    """Build a conversation payload compatible with ingestion."""
    now = datetime.utcnow().isoformat()
    return {
        "conversation_id": response.conversation_id,
        "turns": [
            {
                "turn_id": 1,
                "role": "user",
                "content": response.user_message,
                "timestamp": now,
            },
            {
                "turn_id": 2,
                "role": "assistant",
                "content": response.assistant_message,
                "timestamp": now,
                "tool_calls": [response.tool_call] if response.tool_call else [],
            },
        ],
        "metadata": {
            "source": "demo_agent",
            "prompt_path": str(prompt_path),
        },
    }


def append_turns_payload(
    existing_payload: dict[str, Any],
    user_message: str,
    assistant_message: str,
    tool_call: dict[str, Any] | None,
    prompt_path: Path,
) -> dict[str, Any]:
    """Append a user/assistant turn pair to an existing conversation payload."""
    turns = list(existing_payload.get("turns", []))
    if turns:
        max_turn_id = max(t.get("turn_id", 0) for t in turns)
    else:
        max_turn_id = 0

    now = datetime.utcnow().isoformat()
    turns.append({
        "turn_id": max_turn_id + 1,
        "role": "user",
        "content": user_message,
        "timestamp": now,
    })
    turns.append({
        "turn_id": max_turn_id + 2,
        "role": "assistant",
        "content": assistant_message,
        "timestamp": now,
        "tool_calls": [tool_call] if tool_call else [],
    })

    metadata = dict(existing_payload.get("metadata", {}))
    metadata["prompt_path"] = str(prompt_path)

    return {
        "conversation_id": existing_payload.get("conversation_id"),
        "turns": turns,
        "metadata": metadata,
    }
