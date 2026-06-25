"""Adapter interface + normalized data model shared by the loop and planner.

Each model SDK speaks a different dialect for tool formatting, message history, and
response parsing. A ModelAdapter translates one provider to/from the normalized shapes
below so loop.py and planner.py never branch on which model is running.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolCall:
    name: str
    arguments: dict
    id: str | None = None  # provider-specific call id, when the provider supplies one


@dataclass
class Turn:
    """One normalized model response."""

    text: str
    tool_calls: list[ToolCall]
    input_tokens: int
    output_tokens: int
    raw: Any  # the provider's assistant message/content, replayed verbatim into history


@dataclass
class ToolResult:
    call: ToolCall
    output: str


class ModelAdapter(ABC):
    """Translates one model SDK to/from the normalized shapes the loop understands.

    Knows only how to format tools going in and parse responses coming out — nothing
    about planning, execution order, or metrics.
    """

    name: str       # short id, e.g. "claude"
    model_id: str   # concrete model string, e.g. "claude-sonnet-4-6"

    @abstractmethod
    def format_tools(self, raw_tools: list[dict]) -> Any:
        """Convert raw MCP tool dicts into this provider's tool/function format."""

    @abstractmethod
    def init_messages(self, prompt: str) -> list:
        """Create the initial (user-only) message history in the provider's shape."""

    @abstractmethod
    def add_user_message(self, messages: list, text: str) -> None:
        """Append a plain user-text message (used by the loop to nudge an unfinished plan)."""

    @abstractmethod
    def add_assistant_turn(self, messages: list, turn: Turn) -> None:
        """Append the assistant's turn (including its tool calls) to history."""

    @abstractmethod
    def add_tool_results(self, messages: list, results: list[ToolResult]) -> None:
        """Append tool outputs to history in the provider's shape."""

    @abstractmethod
    def complete(self, system: str, messages: list, tools: Any | None, max_tokens: int) -> Turn:
        """One model call. tools=None means a plain text call (used by the planner)."""
