"""Parallel deliberation: run multiple reasoning branches and pick the best.

For important sub-tasks, spawn N parallel agents with varied system prompts.
Each explores the problem independently, then a selection step picks the best.
This leverages the speed of small models -- running 3 cheap branches in parallel
is faster than one expensive large-model call.
"""
from __future__ import annotations

from typing import Optional

from multi_agent.subagent import SubAgentManager, SubAgentTask


# Prompt variations to encourage diverse approaches
_VARIATIONS = [
    "",  # Branch 0: no modification (baseline)
    (
        "\nApproach this step-by-step. Think carefully about each action "
        "before you take it. Consider edge cases."
    ),
    (
        "\nBe direct and efficient. Use the minimum number of tool calls "
        "to accomplish the task. Prefer simple solutions."
    ),
    (
        "\nBefore acting, briefly analyze what tools and files you'll need. "
        "Then execute your plan in order."
    ),
]


class DeliberationManager:
    """Manages parallel deliberation branches for a single task."""

    def __init__(self, sub_agent_manager: SubAgentManager):
        self.manager = sub_agent_manager

    def deliberate(
        self,
        task_prompt: str,
        config: dict,
        system_prompt: str,
        n_branches: int = 3,
        depth: int = 0,
        timeout: float = 120,
    ) -> Optional[str]:
        """Run N parallel branches and select the best result.

        Args:
            task_prompt: the task to deliberate on
            config: agent configuration
            system_prompt: base system prompt
            n_branches: number of parallel branches (2-4)
            depth: current nesting depth
            timeout: max seconds to wait per branch

        Returns:
            Best result string, or None if all branches failed.
        """
        n_branches = min(n_branches, len(_VARIATIONS), 4)

        # Spawn branches
        tasks: list[SubAgentTask] = []
        for i in range(n_branches):
            branch_system = system_prompt + _VARIATIONS[i % len(_VARIATIONS)]
            task = self.manager.spawn(
                prompt=task_prompt,
                config={**config, "_is_subtask": True},
                system_prompt=branch_system,
                depth=depth,
                name=f"deliberation-{i}",
            )
            tasks.append(task)

        # Wait for all branches
        results: list[tuple[int, str]] = []
        for i, task in enumerate(tasks):
            self.manager.wait(task.id, timeout=timeout)
            if task.status == "completed" and task.result:
                results.append((i, task.result))

        if not results:
            return None
        if len(results) == 1:
            return results[0][1]

        # Select best result using heuristics
        return self._select_best(results, task_prompt)

    def _select_best(
        self,
        results: list[tuple[int, str]],
        original_prompt: str,
    ) -> str:
        """Select the best result from multiple branches.

        Heuristic scoring:
        - Prefer results that mention tool execution (contain tool results)
        - Prefer results that are substantive (not too short, not too long)
        - Prefer results that reference the original task terms
        """
        scores: list[tuple[float, int, str]] = []

        prompt_words = set(original_prompt.lower().split())

        for idx, result in results:
            score = 0.0

            # Length: prefer substantive responses (not too short)
            if len(result) > 50:
                score += 1.0
            if len(result) > 200:
                score += 0.5

            # Relevance: how many prompt words appear in result
            result_lower = result.lower()
            overlap = sum(1 for w in prompt_words if w in result_lower and len(w) > 3)
            score += min(overlap * 0.3, 3.0)

            # Completeness indicators
            if any(w in result_lower for w in ["done", "complete", "created", "updated", "fixed"]):
                score += 1.0

            # Penalize error indicators
            if "error" in result_lower or "failed" in result_lower:
                score -= 2.0
            if "i cannot" in result_lower or "i'm unable" in result_lower:
                score -= 3.0

            scores.append((score, idx, result))

        # Return the highest-scoring result
        scores.sort(reverse=True)
        return scores[0][2]

    def deliberate_on_failure(
        self,
        task_prompt: str,
        failed_result: str,
        config: dict,
        system_prompt: str,
        n_branches: int = 2,
        depth: int = 0,
        timeout: float = 120,
    ) -> Optional[str]:
        """Re-attempt a task after failure using deliberation.

        Includes the failure context so branches can learn from it.
        """
        enhanced_prompt = (
            f"{task_prompt}\n\n"
            f"Note: A previous attempt at this task failed with:\n"
            f"{failed_result[:500]}\n\n"
            f"Please try a different approach."
        )
        return self.deliberate(
            enhanced_prompt, config, system_prompt,
            n_branches=n_branches, depth=depth, timeout=timeout,
        )
