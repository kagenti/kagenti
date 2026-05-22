"""Budget tracking for the plan-execute-reflect reasoning loop.

Prevents runaway execution by capping iterations, tool calls per step,
and total token usage.  When the budget is exceeded the reflector forces
the loop to terminate gracefully.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentBudget:
    """Tracks resource usage across the reasoning loop.

    Attributes
    ----------
    max_iterations:
        Maximum outer-loop iterations (planner → executor → reflector).
    max_tool_calls_per_step:
        Maximum tool invocations the executor may make for a single plan step.
    max_tokens:
        Approximate upper bound on total tokens consumed (prompt + completion).
    hitl_interval:
        After this many iterations, the reflector suggests a human check-in.
    """

    max_iterations: int = 10
    max_tool_calls_per_step: int = 5
    max_tokens: int = 200_000
    hitl_interval: int = 5

    # Mutable runtime counters — not constructor args.
    iterations_used: int = field(default=0, init=False)
    tokens_used: int = field(default=0, init=False)
    tool_calls_this_step: int = field(default=0, init=False)

    # -- helpers -------------------------------------------------------------

    def tick_iteration(self) -> None:
        """Advance the iteration counter by one."""
        self.iterations_used += 1

    def add_tokens(self, count: int) -> None:
        """Accumulate *count* tokens (prompt + completion)."""
        self.tokens_used += count

    def tick_tool_call(self) -> None:
        """Record a tool invocation within the current step."""
        self.tool_calls_this_step += 1

    def reset_step_tools(self) -> None:
        """Reset the per-step tool-call counter (called between plan steps)."""
        self.tool_calls_this_step = 0

    # -- queries -------------------------------------------------------------

    @property
    def iterations_exceeded(self) -> bool:
        return self.iterations_used >= self.max_iterations

    @property
    def tokens_exceeded(self) -> bool:
        return self.tokens_used >= self.max_tokens

    @property
    def step_tools_exceeded(self) -> bool:
        return self.tool_calls_this_step >= self.max_tool_calls_per_step

    @property
    def exceeded(self) -> bool:
        """Return True if *any* budget limit has been reached."""
        return self.iterations_exceeded or self.tokens_exceeded

    @property
    def needs_hitl_checkin(self) -> bool:
        """Return True when it's time for a human-in-the-loop check-in."""
        return (
            self.hitl_interval > 0
            and self.iterations_used > 0
            and self.iterations_used % self.hitl_interval == 0
        )
