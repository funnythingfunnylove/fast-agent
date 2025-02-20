"""
Decorator-based interface for MCP Agent applications.
Provides a simplified way to create and manage agents using decorators.
"""

from typing import List, Optional, Dict, Callable, TypeVar, Generic, Any
from enum import Enum
import yaml
import argparse
from contextlib import asynccontextmanager

from mcp_agent.app import MCPApp
from mcp_agent.agents.agent import Agent, AgentConfig
from mcp_agent.context_dependent import ContextDependent
from mcp_agent.workflows.orchestrator.orchestrator import Orchestrator
from mcp_agent.config import Settings
from rich.prompt import Prompt
from rich import print
from mcp_agent.progress_display import progress_display
from mcp_agent.workflows.llm.model_factory import ModelFactory
from mcp_agent.workflows.llm.augmented_llm import RequestParams

import readline  # noqa: F401

from mcp_agent.workflows.parallel.parallel_llm import ParallelLLM  # noqa: F401
from mcp_agent.workflows.evaluator_optimizer.evaluator_optimizer import (
    EvaluatorOptimizerLLM,
    QualityRating,
)


class AgentType(Enum):
    """Enumeration of supported agent types."""

    BASIC = "agent"
    ORCHESTRATOR = "orchestrator"
    PARALLEL = "parallel"
    EVALUATOR_OPTIMIZER = "evaluator_optimizer"


T = TypeVar("T")  # For the wrapper classes


class BaseAgentWrapper(Generic[T]):
    """
    Base wrapper class for all agent types.

    Provides a consistent interface for different types of agents (basic, orchestrator, parallel)
    by implementing the common protocol expected by the agent application.

    Args:
        agent: The underlying agent implementation
    """

    def __init__(self, agent: T):
        self._llm = agent
        self.name = agent.name

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class MCPAgentDecorator(ContextDependent):
    """
    A decorator-based interface for MCP Agent applications.
    Provides a simplified way to create and manage agents using decorators.
    """

    def __init__(self, name: str, config_path: Optional[str] = None):
        """
        Initialize the decorator interface.

        Args:
            name: Name of the application
            config_path: Optional path to config file
        """
        # Initialize ContextDependent
        super().__init__()

        # Setup command line argument parsing
        parser = argparse.ArgumentParser(description="MCP Agent Application")
        parser.add_argument(
            "--model",
            help="Override the default model for all agents. Precedence is default < config_file < command line < constructor",
        )
        self.args = parser.parse_args()

        self.name = name
        self.config_path = config_path
        self._load_config()
        self.app = MCPApp(
            name=name,
            settings=Settings(**self.config) if hasattr(self, "config") else None,
        )
        self.agents: Dict[str, Dict[str, Any]] = {}

    @property
    def context(self):
        """Access the application context"""
        return self.app.context

    def _load_config(self) -> None:
        """Load configuration from YAML file, properly handling without dotenv processing"""
        if self.config_path:
            with open(self.config_path) as f:
                self.config = yaml.safe_load(f)

    def _get_model_factory(
        self,
        model: Optional[str] = None,
        request_params: Optional[RequestParams] = None,
    ) -> Any:
        """
        Get model factory using specified or default model.
        Model string is parsed by ModelFactory to determine provider and reasoning effort.

        Args:
            model: Optional model specification string
            request_params: Optional RequestParams to configure LLM behavior

        Returns:
            ModelFactory instance for the specified or default model
        """
        print(
            f"\n_get_model_factory called with model={model}, request_params={request_params}"
        )

        # Config has lowest precedence
        model_spec = self.context.config.default_model
        print(f"Starting with config default: {model_spec}")

        # Command line override has next precedence
        if self.args.model:
            model_spec = self.args.model
            print(f"Applied command line override: {model_spec}")

        # Model from decorator has highest precedence
        if model:
            model_spec = model
            print(f"Applied decorator model: {model_spec}")

        print(f"Creating factory with final model_spec: {model_spec}")

        # Update or create request_params with the final model choice
        if request_params:
            request_params = request_params.model_copy(update={"model": model_spec})
        else:
            request_params = RequestParams(model=model_spec)

        # Let model factory handle the model string parsing and setup
        return ModelFactory.create_factory(model_spec, request_params=request_params)

    def agent(
        self,
        name: str,
        instruction: str,
        servers: List[str] = [],
        model: Optional[str] = None,
        use_history: bool = True,
        request_params: Optional[Dict] = None,
    ) -> Callable:
        """
        Decorator to create and register an agent with configuration.

        Args:
            name: Name of the agent
            instruction: Base instruction for the agent
            servers: List of server names the agent should connect to
            model: Model specification string (highest precedence)
            use_history: Whether to maintain conversation history
            request_params: Additional request parameters for the LLM
        """
        print(f"\nDecorating agent {name} with model={model}")

        def decorator(func: Callable) -> Callable:
            # Create base request params with model included
            print(f"\nDecorating {name} with params:")
            print(f"  model={model}")
            print(f"  use_history={use_history}")
            print(f"  request_params={request_params}")
            
            base_params = RequestParams(
                use_history=use_history,
                model=model,  # Include model in initial params
                maxTokens=4096,  # Default to larger context for agents
                **(request_params or {}),
            )
            print(f"Created base_params for {name}: {base_params}")

            # Create agent configuration
            config = AgentConfig(
                name=name,
                instruction=instruction,
                servers=servers,
                model=model,  # Highest precedence
                use_history=use_history,
                default_request_params=base_params,
            )
            print(f"Created config for {name}: {config}")

            # Store the agent configuration
            self.agents[name] = {
                "config": config,
                "type": AgentType.BASIC.value,
                "func": func,
            }
            print(f"Stored agent {name} with config: {self.agents[name]}")

            async def wrapper(*args, **kwargs):
                return await func(*args, **kwargs)

            return wrapper

        return decorator

    def orchestrator(
        self,
        name: str,
        instruction: str,
        agents: List[str],
        model: Optional[str] = None,
        use_history: bool = True,
        request_params: Optional[Dict] = None,
    ) -> Callable:
        """
        Decorator to create and register an orchestrator.

        Args:
            name: Name of the orchestrator
            instruction: Base instruction for the orchestrator
            agents: List of agent names this orchestrator can use
            model: Model specification string (highest precedence)
            use_history: Whether to maintain conversation history
            request_params: Additional request parameters for the LLM
        """

        def decorator(func: Callable) -> Callable:
            # Create base request params
            base_params = RequestParams(
                use_history=use_history, **(request_params or {})
            )

            # Create agent configuration
            config = AgentConfig(
                name=name,
                instruction=instruction,
                servers=[],  # Orchestrators don't need servers
                model=model,  # Highest precedence
                use_history=use_history,
                default_request_params=base_params,
            )

            # Store the orchestrator configuration
            self.agents[name] = {
                "config": config,
                "child_agents": agents,
                "type": AgentType.ORCHESTRATOR.value,
                "func": func,
            }

            async def wrapper(*args, **kwargs):
                return await func(*args, **kwargs)

            return wrapper

        return decorator

    def parallel(
        self,
        name: str,
        fan_in: str,
        fan_out: List[str],
        instruction: str = "",
        model: Optional[str] = None,
        use_history: bool = True,
        request_params: Optional[Dict] = None,
    ) -> Callable:
        """
        Decorator to create and register a parallel executing agent.

        Args:
            name: Name of the parallel executing agent
            fan_in: Name of collecting agent
            fan_out: List of parallel execution agents
            instruction: Optional instruction for the parallel agent
            model: Model specification string
            use_history: Whether to maintain conversation history
            request_params: Additional request parameters for the LLM
        """

        def decorator(func: Callable) -> Callable:
            # Create request params with history setting
            params = RequestParams(**(request_params or {}))
            params.use_history = use_history

            # Create agent configuration
            config = AgentConfig(
                name=name,
                instruction=instruction,
                servers=[],  # Parallel agents don't need servers
                model=model,
                use_history=use_history,
                default_request_params=params,
            )

            # Store the parallel configuration
            self.agents[name] = {
                "config": config,
                "fan_out": fan_out,
                "fan_in": fan_in,
                "type": AgentType.PARALLEL.value,
                "func": func,
            }

            async def wrapper(*args, **kwargs):
                return await func(*args, **kwargs)

            return wrapper

        return decorator

    def evaluator_optimizer(
        self,
        name: str,
        optimizer: str,
        evaluator: str,
        min_rating: str = "GOOD",
        max_refinements: int = 3,
        use_history: bool = True,
        request_params: Optional[Dict] = None,
    ) -> Callable:
        """
        Decorator to create and register an evaluator-optimizer workflow.

        Args:
            name: Name of the workflow
            optimizer: Name of the optimizer agent
            evaluator: Name of the evaluator agent
            min_rating: Minimum acceptable quality rating (EXCELLENT, GOOD, FAIR, POOR)
            max_refinements: Maximum number of refinement iterations
            use_history: Whether to maintain conversation history
            request_params: Additional request parameters for the LLM
        """
        def decorator(func: Callable) -> Callable:
            # Create workflow configuration
            config = AgentConfig(
                name=name,
                instruction="",  # Uses optimizer's instruction
                servers=[],  # Uses agents' server access
                use_history=use_history,
                default_request_params=request_params,
            )

            # Store the workflow configuration
            self.agents[name] = {
                "config": config,
                "optimizer": optimizer,
                "evaluator": evaluator,
                "min_rating": min_rating,
                "max_refinements": max_refinements,
                "type": AgentType.EVALUATOR_OPTIMIZER.value,
                "func": func,
            }

            async def wrapper(*args, **kwargs):
                return await func(*args, **kwargs)

            return wrapper

        return decorator

    def _create_basic_agents(self, agent_app: MCPApp) -> Dict[str, Agent]:
        """
        Create and initialize basic agents with their configurations.

        Args:
            agent_app: The main application instance

        Returns:
            Dictionary of initialized basic agents
        """
        active_agents = {}

        for name, agent_data in self.agents.items():
            if agent_data["type"] == AgentType.BASIC.value:
                config = agent_data["config"]

                # Create agent with configuration
                agent = Agent(config=config, context=agent_app.context)
                active_agents[name] = agent

        return active_agents

    def _create_orchestrators(
        self, agent_app: MCPApp, active_agents: Dict[str, Any]
    ) -> Dict[str, BaseAgentWrapper]:
        """
        Create orchestrator agents.

        Args:
            agent_app: The main application instance
            active_agents: Dictionary of already created agents

        Returns:
            Dictionary of initialized orchestrator agents
        """
        orchestrators = {}
        for name, agent_data in self.agents.items():
            if agent_data["type"] == AgentType.ORCHESTRATOR.value:
                config = agent_data["config"]

                # TODO: Remove legacy - This model/params setup should be in Agent class
                # Resolve model alias if present
                model_config = ModelFactory.parse_model_string(config.model)
                resolved_model = model_config.model_name

                # Start with existing params if available
                if config.default_request_params:
                    base_params = config.default_request_params.model_copy()
                    # Update with orchestrator-specific settings
                    base_params.use_history = config.use_history
                    base_params.model = resolved_model
                else:
                    base_params = RequestParams(
                        use_history=config.use_history, model=resolved_model
                    )

                llm_factory = self._get_model_factory(
                    model=config.model,  # Use original model string for factory creation
                    request_params=base_params,
                )

                # Get the child agents
                child_agents = [
                    active_agents[agent_name]
                    for agent_name in agent_data["child_agents"]
                ]

                orchestrator = Orchestrator(
                    name=config.name,
                    instruction=config.instruction,
                    available_agents=child_agents,
                    context=agent_app.context,
                    llm_factory=llm_factory,
                    request_params=base_params,  # Use our base params that include model
                    plan_type="full",
                )

                orchestrators[name] = BaseAgentWrapper(orchestrator)
        return orchestrators

    async def _create_evaluator_optimizers(
        self, 
        agent_app: MCPApp, 
        active_agents: Dict[str, Any]
    ) -> Dict[str, BaseAgentWrapper]:
        """
        Create evaluator-optimizer workflows.

        Args:
            agent_app: The main application instance
            active_agents: Dictionary of already created agents

        Returns:
            Dictionary of initialized evaluator-optimizer workflows
        """
        workflows = {}
        for name, agent_data in self.agents.items():
            if agent_data["type"] == AgentType.EVALUATOR_OPTIMIZER.value:
                config = agent_data["config"]
                
                # Get the referenced agents
                optimizer = active_agents.get(agent_data["optimizer"])
                evaluator = active_agents.get(agent_data["evaluator"])
                
                if not optimizer or not evaluator:
                    raise ValueError(
                        f"Missing agents for workflow {name}: "
                        f"optimizer={agent_data['optimizer']}, "
                        f"evaluator={agent_data['evaluator']}"
                    )

                # TODO: Remove legacy - factory usage is only needed for str evaluators
                # Later this should only be passed when evaluator is a string
                optimizer_model = optimizer.config.model if isinstance(optimizer, Agent) else None
                workflow = EvaluatorOptimizerLLM(
                    optimizer=optimizer,
                    evaluator=evaluator,
                    min_rating=QualityRating[agent_data["min_rating"]],
                    max_refinements=agent_data["max_refinements"],
                    llm_factory=self._get_model_factory(model=optimizer_model),
                    context=agent_app.context,
                )

                workflows[name] = BaseAgentWrapper(workflow)
                
        return workflows

    def _get_parallel_dependencies(
        self, name: str, visited: set, path: set
    ) -> List[str]:
        """
        Get dependencies for a parallel agent in topological order.

        Args:
            name: Name of the parallel agent
            visited: Set of already visited agents
            path: Current path for cycle detection

        Returns:
            List of agent names in dependency order

        Raises:
            ValueError: If circular dependency detected
        """
        if name in path:
            path_str = " -> ".join(path)
            raise ValueError(f"Circular dependency detected: {path_str} -> {name}")

        if name in visited:
            return []

        if name not in self.agents:
            return []

        config = self.agents[name]
        if config["type"] != AgentType.PARALLEL.value:
            return []

        path.add(name)
        deps = []

        # Get dependencies from fan-out agents
        for fan_out in config["fan_out"]:
            deps.extend(self._get_parallel_dependencies(fan_out, visited, path))

        # Add this agent after its dependencies
        deps.append(name)
        visited.add(name)
        path.remove(name)

        return deps

    def _create_parallel_agents(
        self, agent_app: MCPApp, active_agents: Dict[str, Any]
    ) -> Dict[str, BaseAgentWrapper]:
        """
        Create parallel execution agents in dependency order.

        Args:
            agent_app: The main application instance
            active_agents: Dictionary of already created agents

        Returns:
            Dictionary of initialized parallel agents
        """
        parallel_agents = {}
        visited = set()

        # Get all parallel agents
        parallel_names = [
            name
            for name, agent_data in self.agents.items()
            if agent_data["type"] == AgentType.PARALLEL.value
        ]

        # Create agents in dependency order
        for name in parallel_names:
            # Get ordered dependencies if not already processed
            if name not in visited:
                try:
                    ordered_agents = self._get_parallel_dependencies(
                        name, visited, set()
                    )
                except ValueError as e:
                    raise ValueError(f"Error creating parallel agent {name}: {str(e)}")

                # Create each agent in order
                for agent_name in ordered_agents:
                    if agent_name not in parallel_agents:
                        agent_data = self.agents[agent_name]
                        config = agent_data["config"]

                        # Get fan-out agents (could be basic agents or other parallels)
                        fan_out_agents = []
                        for fan_out_name in agent_data["fan_out"]:
                            if fan_out_name in parallel_agents:
                                fan_out_agents.append(parallel_agents[fan_out_name])
                            else:
                                fan_out_agents.append(active_agents[fan_out_name])

                        # Get fan-in agent
                        fan_in_agent = active_agents[agent_data["fan_in"]]

                        # Create the parallel workflow
                        llm_factory = self._get_model_factory(config.model)
                        parallel = ParallelLLM(
                            name=config.name,
                            instruction=config.instruction,
                            fan_out_agents=fan_out_agents,
                            fan_in_agent=fan_in_agent,
                            context=agent_app.context,
                            llm_factory=llm_factory,
                            default_request_params=config.default_request_params,
                        )

                        parallel_agents[agent_name] = BaseAgentWrapper(parallel)

        return parallel_agents

    @asynccontextmanager
    async def run(self):
        """
        Context manager for running the application.
        Handles setup and teardown of the app and agents.

        Yields:
            AgentAppWrapper instance with all initialized agents
        """
        async with self.app.run() as agent_app:
            # Create all types of agents
            active_agents = {}

            # Set up basic agents with their configurations
            print("\nCreating basic agents:")
            active_agents = {}
            for name, agent_data in self.agents.items():
                if agent_data["type"] == AgentType.BASIC.value:
                    config = agent_data["config"]
                    print(f"\nSetting up agent {name} with config: {config}")

                    # Create agent with configuration
                    agent = Agent(config=config, context=agent_app.context)
                    active_agents[name] = agent
                    print(f"\nCreated agent {name} with config: {config}")

                    # Set up LLM with proper configuration
                    async with agent:
                        print(f"Creating LLM factory for {name}:")
                        print(f"  Using config model: {config.model}")
                        print(f"  Using request params: {config.default_request_params}")
                        llm_factory = self._get_model_factory(
                            model=config.model, 
                            request_params=config.default_request_params
                        )
                        print(f"  Created factory: {llm_factory}")
                        agent._llm = await agent.attach_llm(llm_factory)
                        print(f"  Created LLM: {agent._llm}")

            print("\nCreating orchestrators:")
            # Create workflow agents
            orchestrators = self._create_orchestrators(agent_app, active_agents)
            print("\nCreating parallel workflows:")
            parallel_agents = self._create_parallel_agents(agent_app, active_agents)
            print("\nCreating evaluator-optimizer workflows:")
            evaluator_optimizers = await self._create_evaluator_optimizers(agent_app, active_agents)

            # Merge all agents into active_agents
            active_agents.update(orchestrators)
            active_agents.update(parallel_agents)
            active_agents.update(evaluator_optimizers)

            # Create wrapper with all agents
            wrapper = AgentAppWrapper(agent_app, active_agents)
            try:
                yield wrapper
            finally:
                # Clean up basic agents
                for name, agent in active_agents.items():
                    if isinstance(agent, Agent):
                        await agent.__aexit__(None, None, None)


class AgentAppWrapper:
    """
    Wrapper class providing a simplified interface to the agent application.
    Manages communication with agents and provides interactive prompting.
    """

    def __init__(self, app: MCPApp, agents: Dict[str, Any]):
        self.app = app
        self.agents = agents
        self._default_agent = next(iter(agents)) if agents else None

    async def send(self, agent_name: str, message: str) -> Any:
        """
        Send a message to a specific agent and get the response.

        Args:
            agent_name: Name of the target agent
            message: Message to send

        Returns:
            Agent's response

        Raises:
            ValueError: If agent not found
            RuntimeError: If agent has no LLM attached
        """
        if agent_name not in self.agents:
            raise ValueError(f"Agent {agent_name} not found")

        agent = self.agents[agent_name]
        if not hasattr(agent, "_llm") or agent._llm is None:
            raise RuntimeError(f"Agent {agent_name} has no LLM attached")
        return await agent._llm.generate_str(message)

    async def __call__(self, message: str, agent_name: Optional[str] = None) -> Any:
        """
        Send a message using direct call syntax.

        Args:
            message: Message to send
            agent_name: Optional target agent name (uses default if not specified)

        Returns:
            Agent's response
        """
        target_agent = agent_name or self._default_agent
        if not target_agent:
            raise ValueError("No agents available")
        return await self.send(target_agent, message)

    async def prompt(self, agent_name: Optional[str] = None, default: str = "") -> None:
        """
        Interactive prompt for sending messages.

        Args:
            agent_name: Optional target agent name (uses default if not specified)
            default: Default message to use when user presses enter
        """
        target_agent = agent_name or self._default_agent
        if not target_agent:
            raise ValueError("No agents available")

        while True:
            with progress_display.paused():
                if default == "STOP":
                    print("Press <ENTER> to finish.")
                elif default != "":
                    print("Enter a prompt, or [red]STOP[/red] to finish.")
                    print(
                        f"Press <ENTER> to use the default prompt:\n[cyan]{default}[/cyan]"
                    )
                else:
                    print("Enter a prompt, or [red]STOP[/red] to finish")

                prompt_text = f"[blue]{target_agent}[/blue] >"
                user_input = Prompt.ask(
                    prompt=prompt_text, default=default, show_default=False
                )

                if user_input.upper() == "STOP":
                    return

            await self.send(target_agent, user_input)
