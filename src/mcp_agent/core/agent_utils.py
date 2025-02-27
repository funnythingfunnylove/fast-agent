"""
Utility functions for agent operations.
"""

from typing import List

from mcp_agent.core.proxies import BaseAgentProxy, LLMAgentProxy
from mcp_agent.core.types import AgentOrWorkflow, ProxyDict
from mcp_agent.event_progress import ProgressAction


def unwrap_proxy(proxy: BaseAgentProxy) -> AgentOrWorkflow:
    """
    Unwrap a proxy to get the underlying agent or workflow instance.

    Args:
        proxy: The proxy object to unwrap

    Returns:
        The underlying Agent or workflow instance
    """
    if isinstance(proxy, LLMAgentProxy):
        return proxy._agent
    return proxy._workflow


def get_agent_instances(
    agent_names: List[str], active_agents: ProxyDict
) -> List[AgentOrWorkflow]:
    """
    Get list of actual agent/workflow instances from a list of names.

    Args:
        agent_names: List of agent names to look up
        active_agents: Dictionary of active agent proxies

    Returns:
        List of unwrapped agent/workflow instances
    """
    return [unwrap_proxy(active_agents[name]) for name in agent_names]


def log_agent_load(app, agent_name: str) -> None:
    """
    Log agent loading event to application logger.
    
    Args:
        app: The application instance
        agent_name: Name of the agent being loaded
    """
    app._logger.info(
        f"Loaded {agent_name}",
        data={
            "progress_action": ProgressAction.LOADED,
            "agent_name": agent_name,
        },
    )