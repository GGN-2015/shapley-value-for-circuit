from fractions import Fraction

import pytest
from circuit_static_description import Circuit

from shapley_value_for_circuit import (
    LocalShapleyError,
    calculate_shapley_values,
    explain,
    load_circuit,
    shapley_values,
)


def assert_conserves(result):
    assert result.base_value + sum(result.values) == result.output_value


def test_and_gate_splits_credit_equally_for_true_true():
    circuit = Circuit(2, 1, outputs=["AND(I0, I1)"])

    result = explain(circuit, [1, 1], 0)

    assert result.output_value == 1
    assert result.base_value == 0
    assert result.values == (Fraction(1, 2), Fraction(1, 2))
    assert_conserves(result)


def test_and_gate_gives_no_credit_when_output_matches_baseline():
    circuit = Circuit(2, 1, outputs=["AND(I0, I1)"])

    result = explain(circuit, [1, 0], "OUT0")

    assert result.output_value == 0
    assert result.base_value == 0
    assert result.values == (Fraction(0), Fraction(0))
    assert_conserves(result)


def test_or_gate_splits_redundant_true_inputs():
    circuit = Circuit(2, 1, outputs=["OR(I0, I1)"])

    result = explain(circuit, [1, 1])

    assert result.output_value == 1
    assert result.values == (Fraction(1, 2), Fraction(1, 2))
    assert_conserves(result)


def test_xor_gate_assigns_zero_for_double_flip_from_zero_baseline():
    circuit = Circuit(2, 1, outputs=["XOR(I0, I1)"])

    result = explain(circuit, [1, 1])

    assert result.output_value == 0
    assert result.values == (Fraction(0), Fraction(0))
    assert_conserves(result)


def test_not_gate_can_propagate_negative_credit():
    circuit = Circuit(1, 1, outputs=["NOT(I0)"])

    result = explain(circuit, [1])

    assert result.output_value == 0
    assert result.base_value == 1
    assert result.values == (Fraction(-1),)
    assert_conserves(result)


def test_variables_and_nested_gates_are_supported():
    circuit = Circuit(
        3,
        1,
        variables=[("V0", "AND(I0, I1)")],
        outputs=["OR(V0, I2)"],
    )

    result = explain(circuit, [1, 1, 0])

    assert result.output_value == 1
    assert result.values == (Fraction(1, 2), Fraction(1, 2), Fraction(0))
    assert_conserves(result)


def test_custom_baseline_inputs_are_supported():
    circuit = Circuit(1, 1, outputs=["I0"])

    result = explain(circuit, [0], baseline_inputs=[1])

    assert result.output_value == 0
    assert result.base_value == 1
    assert result.values == (Fraction(-1),)
    assert result.baseline_input_values == (1,)
    assert_conserves(result)


def test_text_source_is_loaded_with_circuit_static_description():
    text = """
    INPUTS 2
    OUTPUTS 1
    OUT0 = NAND(I0, I1)
    """

    circuit = load_circuit(text)
    result = explain(circuit, [1, 1])

    assert result.output_value == 0
    assert result.base_value == 1
    assert result.values == (Fraction(-1, 2), Fraction(-1, 2))
    assert_conserves(result)


def test_vector_helpers_return_dense_values():
    circuit = Circuit(2, 1, outputs=["OR(I0, I1)"])

    assert shapley_values(circuit, [1, 0]) == [Fraction(1), Fraction(0)]
    assert calculate_shapley_values(circuit, [1, 0], as_float=True) == [1.0, 0.0]


def test_invalid_output_index_raises_local_error():
    circuit = Circuit(1, 1, outputs=["I0"])

    with pytest.raises(LocalShapleyError):
        explain(circuit, [1], 1)
