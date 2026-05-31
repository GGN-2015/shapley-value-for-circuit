"""Polynomial circuit-local Shapley propagation."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction
from os import PathLike
from pathlib import Path
from typing import Any, Mapping, Sequence, TypeAlias

from circuit_static_description import Circuit

CircuitSource: TypeAlias = Circuit | str | PathLike[str]


class LocalShapleyError(ValueError):
    """Raised when circuit-local Shapley attribution cannot be computed."""


@dataclass(frozen=True)
class ShapleyResult:
    """Attribution result for one output on one sample.

    The conservation identity is:

        baseline_output_value + sum(values) == output_value

    for the circuit-local propagation game.
    """

    values: tuple[Fraction, ...]
    output_index: int
    output_value: int
    baseline_output_value: int
    input_values: tuple[int, ...]
    baseline_input_values: tuple[int, ...]
    method: str = "circuit-local"

    @property
    def base_value(self) -> int:
        """Alias for the output value at the baseline input."""

        return self.baseline_output_value

    def as_floats(self) -> tuple[float, ...]:
        """Return the attribution values as floats."""

        return tuple(float(value) for value in self.values)

    def nonzero_values(self) -> dict[int, Fraction]:
        """Return a sparse mapping of non-zero input attributions."""

        return {
            index: value
            for index, value in enumerate(self.values)
            if value != 0
        }


@dataclass(frozen=True)
class _NodeExplanation:
    value: bool
    baseline_value: bool
    attributions: Mapping[int, Fraction]


def load_circuit(source: CircuitSource) -> Circuit:
    """Load or normalize a circuit.

    ``Circuit`` instances are returned unchanged. Path-like values are loaded
    with ``Circuit.load``. Strings containing circuit text are parsed with
    ``Circuit.from_text``; other strings are treated as paths when they exist.
    """

    if isinstance(source, Circuit):
        return source

    if isinstance(source, str):
        text = source.strip()
        looks_like_text = "\n" in source or text.upper().startswith("INPUTS ")
        if looks_like_text:
            return Circuit.from_text(source)

        path = Path(source)
        if path.exists():
            return Circuit.load(path)

        return Circuit.from_text(source)

    return Circuit.load(Path(source))


def explain(
    circuit: CircuitSource,
    inputs: Sequence[Any],
    output: int | str = 0,
    *,
    baseline_inputs: Sequence[Any] | bool | None = None,
) -> ShapleyResult:
    """Explain one circuit output for one input sample.

    This computes circuit-local Shapley values: each logic gate is explained by
    the exact Shapley values of its one- or two-wire local game, then those
    local attributions are propagated through the upstream attribution vectors.
    The runtime is polynomial in the circuit size and input count.
    """

    normalized_circuit = load_circuit(circuit)
    input_values = _normalize_inputs(inputs, normalized_circuit.get_input_count(), "inputs")
    baseline_values = _normalize_baseline(
        baseline_inputs,
        normalized_circuit.get_input_count(),
    )
    output_index = _normalize_output_index(
        output,
        normalized_circuit.get_output_count(),
    )

    evaluator = _CircuitLocalShapleyEvaluator(
        normalized_circuit,
        input_values,
        baseline_values,
    )
    node = evaluator.output_node(output_index)
    explanation = evaluator.explain_node(node)
    dense_values = _to_dense_tuple(
        explanation.attributions,
        normalized_circuit.get_input_count(),
    )

    result = ShapleyResult(
        values=dense_values,
        output_index=output_index,
        output_value=int(explanation.value),
        baseline_output_value=int(explanation.baseline_value),
        input_values=tuple(int(value) for value in input_values),
        baseline_input_values=tuple(int(value) for value in baseline_values),
    )
    _ensure_conservation(result)
    return result


def shapley_values(
    circuit: CircuitSource,
    inputs: Sequence[Any],
    output: int | str = 0,
    *,
    baseline_inputs: Sequence[Any] | bool | None = None,
    as_float: bool = False,
) -> list[Fraction] | list[float]:
    """Return only the dense input attribution vector."""

    result = explain(
        circuit,
        inputs,
        output,
        baseline_inputs=baseline_inputs,
    )
    if as_float:
        return list(result.as_floats())
    return list(result.values)


def calculate_shapley_values(
    circuit: CircuitSource,
    inputs: Sequence[Any],
    output: int | str = 0,
    *,
    baseline_inputs: Sequence[Any] | bool | None = None,
    as_float: bool = False,
) -> list[Fraction] | list[float]:
    """Compatibility alias for ``shapley_values``."""

    return shapley_values(
        circuit,
        inputs,
        output,
        baseline_inputs=baseline_inputs,
        as_float=as_float,
    )


class _CircuitLocalShapleyEvaluator:
    def __init__(
        self,
        circuit: Circuit,
        inputs: Sequence[bool],
        baseline_inputs: Sequence[bool],
    ) -> None:
        self.circuit = circuit
        self.inputs = inputs
        self.baseline_inputs = baseline_inputs
        self.graph = circuit._ensure_compiled_graph()
        self._variable_cache: dict[int, _NodeExplanation] = {}

    def output_node(self, output_index: int) -> Any:
        return self.graph.output_nodes[output_index]

    def explain_node(self, node: Any) -> _NodeExplanation:
        op = node.op
        if op == "INPUT":
            input_index = _required_int(node.input_index, "input_index")
            value = self.inputs[input_index]
            baseline_value = self.baseline_inputs[input_index]
            delta = _bit(value) - _bit(baseline_value)
            attributions = {input_index: Fraction(delta)} if delta else {}
            return _NodeExplanation(value, baseline_value, attributions)

        if op == "CONSTANT":
            value = bool(node.constant_value)
            return _NodeExplanation(value, value, {})

        if op == "VARIABLE":
            variable_index = _required_int(node.variable_index, "variable_index")
            cached = self._variable_cache.get(variable_index)
            if cached is None:
                cached = self.explain_node(self.graph.variable_nodes[variable_index])
                self._variable_cache[variable_index] = cached
            return cached

        child_explanations = [self.explain_node(child) for child in node.args]
        actual_values = tuple(child.value for child in child_explanations)
        baseline_values = tuple(child.baseline_value for child in child_explanations)
        value = _evaluate_gate(op, actual_values)
        baseline_value = _evaluate_gate(op, baseline_values)
        local_values = _local_gate_shapley(op, actual_values, baseline_values)

        attributions: defaultdict[int, Fraction] = defaultdict(Fraction)
        for child, local_value in zip(child_explanations, local_values):
            if local_value == 0:
                continue

            child_delta = _bit(child.value) - _bit(child.baseline_value)
            if child_delta == 0:
                raise LocalShapleyError(
                    f"Gate {op} assigned non-zero local attribution to an unchanged child"
                )

            scale = local_value / child_delta
            for input_index, attribution in child.attributions.items():
                propagated = attribution * scale
                if propagated:
                    attributions[input_index] += propagated

        return _NodeExplanation(
            value=value,
            baseline_value=baseline_value,
            attributions=dict(attributions),
        )


def _local_gate_shapley(
    op: str,
    actual_values: Sequence[bool],
    baseline_values: Sequence[bool],
) -> tuple[Fraction, ...]:
    arity = len(actual_values)
    if arity != len(baseline_values):
        raise LocalShapleyError("Actual and baseline arities do not match")

    if arity == 1:
        return (
            Fraction(
                _bit(_evaluate_gate(op, actual_values))
                - _bit(_evaluate_gate(op, baseline_values))
            ),
        )

    if arity == 2:
        a0, a1 = actual_values
        b0, b1 = baseline_values
        f = _evaluate_gate
        player0 = Fraction(
            _bit(f(op, (a0, b1))) - _bit(f(op, (b0, b1)))
            + _bit(f(op, (a0, a1))) - _bit(f(op, (b0, a1))),
            2,
        )
        player1 = Fraction(
            _bit(f(op, (b0, a1))) - _bit(f(op, (b0, b1)))
            + _bit(f(op, (a0, a1))) - _bit(f(op, (a0, b1))),
            2,
        )
        return (player0, player1)

    raise LocalShapleyError(f"Unsupported gate arity for {op}: {arity}")


def _evaluate_gate(op: str, values: Sequence[bool]) -> bool:
    if op == "AND":
        _require_arity(op, values, 2)
        return values[0] and values[1]
    if op == "OR":
        _require_arity(op, values, 2)
        return values[0] or values[1]
    if op == "NOT":
        _require_arity(op, values, 1)
        return not values[0]
    if op == "XOR":
        _require_arity(op, values, 2)
        return values[0] ^ values[1]
    if op == "NAND":
        _require_arity(op, values, 2)
        return not (values[0] and values[1])
    if op == "NOR":
        _require_arity(op, values, 2)
        return not (values[0] or values[1])
    raise LocalShapleyError(f"Unsupported operator during attribution: {op}")


def _normalize_inputs(
    values: Sequence[Any],
    expected_count: int,
    name: str,
) -> tuple[bool, ...]:
    if len(values) != expected_count:
        raise LocalShapleyError(
            f"Expected {expected_count} {name} values, got {len(values)}"
        )
    return tuple(bool(value) for value in values)


def _normalize_baseline(
    baseline_inputs: Sequence[Any] | bool | None,
    expected_count: int,
) -> tuple[bool, ...]:
    if baseline_inputs is None:
        return tuple(False for _ in range(expected_count))

    if isinstance(baseline_inputs, bool):
        return tuple(baseline_inputs for _ in range(expected_count))

    return _normalize_inputs(baseline_inputs, expected_count, "baseline input")


def _normalize_output_index(output: int | str, output_count: int) -> int:
    if isinstance(output, int):
        output_index = output
    else:
        output_text = output.strip().upper()
        if output_text.startswith("OUT"):
            output_text = output_text[3:]
        if not output_text.isdigit():
            raise LocalShapleyError(
                f"Expected output index or OUT<number>, got {output!r}"
            )
        output_index = int(output_text)

    if output_index < 0 or output_index >= output_count:
        raise LocalShapleyError(
            f"Output index {output_index} is outside OUTPUTS {output_count}"
        )
    return output_index


def _to_dense_tuple(
    sparse_values: Mapping[int, Fraction],
    input_count: int,
) -> tuple[Fraction, ...]:
    return tuple(sparse_values.get(index, Fraction(0)) for index in range(input_count))


def _require_arity(op: str, values: Sequence[bool], expected: int) -> None:
    if len(values) != expected:
        raise LocalShapleyError(
            f"Operator {op} expects {expected} values, got {len(values)}"
        )


def _required_int(value: int | None, name: str) -> int:
    if value is None:
        raise LocalShapleyError(f"Compiled circuit node is missing {name}")
    return value


def _bit(value: bool) -> int:
    return 1 if value else 0


def _ensure_conservation(result: ShapleyResult) -> None:
    total = Fraction(result.baseline_output_value) + sum(result.values, start=Fraction(0))
    if total != result.output_value:
        raise LocalShapleyError(
            "Local Shapley conservation failed: "
            f"{result.baseline_output_value} + {sum(result.values)} != "
            f"{result.output_value}"
        )
