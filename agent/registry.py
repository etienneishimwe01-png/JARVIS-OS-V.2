"""Central registry for the actions available to the JARVIS agent."""

from dataclasses import dataclass, field
from enum import Enum
from importlib import import_module
from typing import Any, Callable


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ConfirmationRequired(PermissionError):
    """Raised when a task needs explicit user approval before execution."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    category: str
    handler_module: str
    handler_name: str
    parameters: dict[str, str] = field(default_factory=dict)
    required: tuple[str, ...] = ()
    risk: RiskLevel = RiskLevel.LOW
    requires_confirmation: bool = False

    def load_handler(self) -> Callable[..., Any]:
        return getattr(import_module(self.handler_module), self.handler_name)

    def validate(self, parameters: dict[str, Any] | None) -> list[str]:
        values = parameters or {}
        return [key for key in self.required if values.get(key) in (None, "")]

    def needs_confirmation(self, parameters: dict[str, Any] | None) -> bool:
        if not self.requires_confirmation:
            return False
        action = str((parameters or {}).get("action", "")).strip().lower()
        if self.name == "file_controller":
            return action not in {"list", "read", "find", "largest", "disk_usage", "info", "open"}
        if self.name == "email_control":
            return action not in {"status", "inbox", "unread", "search", "read", "cancel"}
        return True


def _spec(name, description, category, module, handler, *, required=(), risk=RiskLevel.LOW, confirm=False):
    return ToolSpec(name, description, category, module, handler, required=required, risk=risk, requires_confirmation=confirm)


_TOOLS = (
    _spec("open_app", "Open a desktop application.", "system", "actions.open_app", "open_app", required=("app_name",)),
    _spec("web_search", "Search the web.", "research", "actions.web_search", "web_search", required=("query",)),
    _spec("deep_research", "Perform source-grounded research.", "research", "actions.deep_research", "deep_research", required=("question",)),
    _spec("browser_control", "Navigate and interact with a browser.", "browser", "actions.browser_control", "browser_control", required=("action",)),
    _spec("file_controller", "Read and manage files under JARVIS safe roots.", "files", "actions.file_controller", "file_controller", required=("action",), risk=RiskLevel.MEDIUM, confirm=True),
    _spec("media_control", "Control supported media playback.", "media", "actions.media_control", "media_control", required=("action",)),
    _spec("computer_settings", "Inspect or change computer settings.", "system", "actions.computer_settings", "computer_settings", required=("action",), risk=RiskLevel.MEDIUM, confirm=True),
    _spec("computer_control", "Interact with the desktop using input or screen tools.", "system", "actions.computer_control", "computer_control", required=("action",), risk=RiskLevel.MEDIUM, confirm=True),
    _spec("desktop_control", "Perform desktop management operations.", "system", "actions.desktop", "desktop_control", required=("action",), risk=RiskLevel.MEDIUM, confirm=True),
    _spec("screen_process", "Analyze the current screen.", "system", "actions.screen_processor", "screen_process", required=("text",)),
    _spec("send_message", "Send an external message.", "communication", "actions.send_message", "send_message", required=("receiver", "message_text", "platform"), risk=RiskLevel.MEDIUM, confirm=True),
    _spec("email_control", "Read or prepare email.", "communication", "actions.email_control", "email_control", required=("action",), risk=RiskLevel.MEDIUM, confirm=True),
    _spec("reminder", "Create a reminder.", "productivity", "actions.reminder", "reminder", required=("date", "time", "message")),
    _spec("youtube_video", "Find or summarize YouTube videos.", "media", "actions.youtube_video", "youtube_video", required=("action",)),
    _spec("weather_report", "Open a weather report.", "research", "actions.weather_report", "weather_action", required=("city",)),
    _spec("flight_finder", "Find flight options.", "research", "actions.flight_finder", "flight_finder", required=("origin", "destination", "date")),
    _spec("game_updater", "Install or update games.", "system", "actions.game_updater", "game_updater", required=("action",), risk=RiskLevel.MEDIUM, confirm=True),
    _spec("code_helper", "Write, edit, run, or explain code.", "development", "actions.code_helper", "code_helper", required=("action", "description"), risk=RiskLevel.MEDIUM, confirm=True),
    _spec("dev_agent", "Assist with a development task.", "development", "actions.dev_agent", "dev_agent", required=("description",), risk=RiskLevel.MEDIUM, confirm=True),
    _spec("create_presentation", "Create a presentation.", "content", "actions.presentation_maker", "create_presentation", required=("topic",), risk=RiskLevel.MEDIUM),
)

TOOL_REGISTRY = {tool.name: tool for tool in _TOOLS}


def get_tool(name: str) -> ToolSpec | None:
    return TOOL_REGISTRY.get(str(name or "").strip())


def discover_tools() -> list[ToolSpec]:
    return list(TOOL_REGISTRY.values())


def tool_descriptions() -> str:
    return "\n".join(f"{tool.name}: {tool.description} ({tool.risk.value} risk)" for tool in discover_tools())