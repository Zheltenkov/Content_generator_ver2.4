"""
content_gen/agents/flow.py

Модель и рантайм для AgentFlow (оркестрация агентов/фаз).
"""

from __future__ import annotations

import ast
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from ..methodology.decision import MethodologyGateInterrupt
from ..utils.cancellation import CancellationToken, CancelledError
from ..utils.progress import ProgressTracker


class FlowNodeConfig(BaseModel):
    """Узел графа агента."""

    id: str
    name: str
    handler: str
    type: str = "agent"
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    conditions: dict[str, str] = Field(default_factory=dict)


class FlowEdgeConfig(BaseModel):
    """Ребро графа (упорядочивает узлы и описывает условия перехода)."""

    source: str
    target: str
    condition: str | None = None


class FlowDefinition(BaseModel):
    """Полный граф AgentFlow."""

    name: str
    version: str
    nodes: list[FlowNodeConfig]
    edges: list[FlowEdgeConfig]


class FlowLibrary(BaseModel):
    """Коллекция доступных флоу."""

    flows: dict[str, FlowDefinition]


@dataclass
class FlowNodeOutput:
    """Стандартный ответ узла для рантайма."""

    updates: dict[str, object] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    status: Literal["success", "skipped", "error"] = "success"


@dataclass
class FlowExecutionStep:
    """Лог одного шага Flow."""

    node_id: str
    node_name: str
    status: Literal["success", "skipped", "error", "cancelled", "paused"]
    duration_ms: float
    issues: list[str] = field(default_factory=list)

    def as_dict(self, index: int) -> dict[str, object]:
        return {
            "step_index": index,
            "node_id": self.node_id,
            "node_name": self.node_name,
            "status": self.status,
            "duration_ms": round(self.duration_ms, 2),
            "issues": self.issues,
        }


class AgentFlowRunner:
    """Исполнитель графа агентов по конфигу."""

    def __init__(
        self,
        definition: FlowDefinition,
        cancellation_token: CancellationToken = None,
        progress_tracker: ProgressTracker = None,
        stage_review_hook: Callable[[FlowNodeConfig, dict[str, object], FlowNodeOutput], list[str]] | None = None,
    ):
        self.definition = definition
        self.node_map = {node.id: node for node in definition.nodes}
        self.execution_plan = self._build_execution_plan(definition)
        self.cancellation_token = cancellation_token or CancellationToken()
        self.progress_tracker = progress_tracker or ProgressTracker()
        self.stage_review_hook = stage_review_hook

    def run(
        self,
        context: dict[str, object],
        registry: dict[str, Callable[[dict[str, object]], FlowNodeOutput]],
        start_index: int = 0,
        previous_steps: list[FlowExecutionStep] | None = None,
    ) -> list[FlowExecutionStep]:
        """Выполняет граф, возвращает лог шагов."""
        steps: list[FlowExecutionStep] = list(previous_steps or [])
        total_nodes = len(self.execution_plan)
        start_index = max(0, min(start_index, total_nodes))

        for idx, node_id in enumerate(self.execution_plan[start_index:], start_index + 1):
            # Проверка на отмену перед каждым узлом
            self.cancellation_token.check()

            # Обновляем прогресс
            self.progress_tracker.update(
                phase="flow",
                current=idx,
                total=total_nodes,
                message=f"Выполнение узла: {node_id}"
            )

            node = self.node_map[node_id]
            if self._should_skip_node(node, context):
                steps.append(
                    FlowExecutionStep(
                        node_id=node.id,
                        node_name=node.name,
                        status="skipped",
                        duration_ms=0.0,
                        issues=["condition=false"],
                    )
                )
                state = context.get("state")
                if hasattr(state, "sync_from_context"):
                    state.sync_from_context(context)
                continue
            handler = registry.get(node.handler)
            start = time.time()
            if handler is None:
                raise RuntimeError(f"Handler '{node.handler}' is not registered for node '{node.id}'")
            try:
                output = handler(context)
                if not isinstance(output, FlowNodeOutput):
                    raise TypeError(
                        f"Handler '{node.handler}' должен возвращать FlowNodeOutput, получено {type(output)}"
                    )

                # Проверка на отмену после обработки
                self.cancellation_token.check()

                context.update(output.updates or {})
                state = context.get("state")
                if hasattr(state, "apply_updates"):
                    state.apply_updates(output.updates or {})
                if hasattr(state, "sync_from_context"):
                    state.sync_from_context(context)
                review_issues: list[str] = []
                if self.stage_review_hook is not None:
                    try:
                        review_issues = self.stage_review_hook(node, context, output) or []
                    except Exception as exc:  # noqa: BLE001
                        if isinstance(exc, MethodologyGateInterrupt):
                            raise
                        review_issues = [f"methodology_gate_error: {exc}"]
                    if hasattr(state, "sync_from_context"):
                        state.sync_from_context(context)
                duration_ms = (time.time() - start) * 1000
                steps.append(
                    FlowExecutionStep(
                        node_id=node.id,
                        node_name=node.name,
                        status=output.status,
                        duration_ms=duration_ms,
                        issues=[*(output.issues or []), *review_issues],
                    )
                )
                if output.status == "error":
                    break
            except MethodologyGateInterrupt as exc:
                duration_ms = (time.time() - start) * 1000
                pause_step = FlowExecutionStep(
                    node_id=node.id,
                    node_name=node.name,
                    status="paused",
                    duration_ms=duration_ms,
                    issues=[str(exc)],
                )
                steps.append(pause_step)
                # idx is 1-based, therefore it is also the zero-based index of the next node.
                exc.attach_flow_state(
                    flow_context=context,
                    flow_steps=steps,
                    resume_from_index=idx,
                )
                raise
            except CancelledError as exc:
                duration_ms = (time.time() - start) * 1000
                steps.append(
                    FlowExecutionStep(
                        node_id=node.id,
                        node_name=node.name,
                        status="cancelled",
                        duration_ms=duration_ms,
                        issues=[f"Отменено: {exc.reason}"],
                    )
                )
                break
            except Exception as exc:  # noqa: BLE001
                duration_ms = (time.time() - start) * 1000
                steps.append(
                    FlowExecutionStep(
                        node_id=node.id,
                        node_name=node.name,
                        status="error",
                        duration_ms=duration_ms,
                        issues=[str(exc)],
                    )
                )
                raise
        return steps

    def _should_skip_node(self, node: FlowNodeConfig, context: dict[str, object]) -> bool:
        """Evaluate optional node conditions from YAML config."""
        if not node.conditions:
            return False

        run_if = node.conditions.get("run_if")
        if run_if and not self._evaluate_condition(run_if, context):
            return True

        skip_if = node.conditions.get("skip_if")
        if skip_if and self._evaluate_condition(skip_if, context):
            return True

        return False

    def _evaluate_condition(self, expression: str, context: dict[str, object]) -> bool:
        """Safely evaluate a small boolean expression against the flow context."""
        safe_globals = {"__builtins__": {}}
        safe_locals = {
            key: value
            for key, value in context.items()
            if key != "state"
        }
        state = context.get("state")
        if hasattr(state, "model_dump"):
            try:
                safe_locals.update(state.model_dump(exclude_none=True, mode="python"))
            except Exception:
                pass

        try:
            parsed = ast.parse(expression, mode="eval")
            compiled = compile(parsed, "<flow-condition>", "eval")
            return bool(eval(compiled, safe_globals, safe_locals))
        except Exception:
            return False

    def _build_execution_plan(self, definition: FlowDefinition) -> list[str]:
        """Вычисляет топологический порядок исполнения."""
        indegree: dict[str, int] = {node.id: 0 for node in definition.nodes}
        adjacency: dict[str, list[str]] = {node.id: [] for node in definition.nodes}
        for edge in definition.edges:
            adjacency[edge.source].append(edge.target)
            indegree[edge.target] += 1

        queue = [node_id for node_id, deg in indegree.items() if deg == 0]
        plan: list[str] = []
        while queue:
            current = queue.pop(0)
            plan.append(current)
            for neighbor in adjacency[current]:
                indegree[neighbor] -= 1
                if indegree[neighbor] == 0:
                    queue.append(neighbor)

        if len(plan) != len(definition.nodes):
            raise RuntimeError("AgentFlow содержит цикл или некорректные зависимости")
        return plan


def load_flow_definition(flow_name: str = "content_generation") -> FlowDefinition:
    """Загружает FlowDefinition из YAML."""
    config_path = Path(__file__).resolve().parents[1] / "config" / "flow.yaml"
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    library = FlowLibrary(**raw)
    if flow_name not in library.flows:
        raise KeyError(f"Flow '{flow_name}' не найден в config/flow.yaml")
    return library.flows[flow_name]

