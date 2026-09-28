"""Agent layer: the SDK behind an interface, with a real and a fake client."""

from vibing.agent.base import (
    AgentClient,
    AgentError,
    AgentFactory,
    AgentOptions,
    PermissionCallback,
)

__all__ = [
    "AgentClient",
    "AgentError",
    "AgentFactory",
    "AgentOptions",
    "PermissionCallback",
]
