# shapley-value-for-circuit

Polynomial circuit-local Shapley attribution for a single boolean circuit sample.

This package uses
[`circuit-static-description`](https://pypi.org/project/circuit-static-description/)
to load, parse, and validate circuits. Given a circuit, a complete input sample,
and one output index, it returns the attribution of that output to each original
input.

## Installation

```bash
pip install -e .
```

For development and tests:

```bash
pip install -e .[test]
pytest
```

For heatmap visualization:

```bash
pip install -e .[viz]
```

## Quick Start

```python
from circuit_static_description import Circuit
from shapley_value_for_circuit import explain, shapley_values

circuit = Circuit(
    2,  # Number of inputs.
    1,  # Number of outputs.
    outputs=["AND(I0, I1)"],
)

result = explain(circuit, inputs=[1, 1], output=0)

print(result.values)
# Attribution for each original input:
# I0 contributes 1/2, and I1 contributes 1/2.
# (Fraction(1, 2), Fraction(1, 2))

print(result.base_value, result.output_value)
# The target output is 0 on the all-zero baseline input,
# and 1 on the current input [1, 1].
# 0 1

print(shapley_values(circuit, [1, 1], as_float=True))
# Same attributions returned as floats.
# [0.5, 0.5]
```

You can also pass circuit text in the `circuit-static-description` format:

```python
from shapley_value_for_circuit import explain

text = """
INPUTS 3
OUTPUTS 1
V0 = AND(I0, I1)
OUT0 = OR(V0, I2)
"""

result = explain(text, inputs=[1, 1, 0], output="OUT0")
print(result.values)
# I0 and I1 explain V0 = AND(I0, I1).
# I2 is unchanged from the baseline, so its contribution is 0.
# (Fraction(1, 2), Fraction(1, 2), Fraction(0, 1))
```

## Intuition

The circuit output is boolean, so `result.base_value` and
`result.output_value` are always either `0` or `1`. The attribution values are
not restricted to booleans: they explain how the output changed from the
baseline sample to the current sample.

With the default all-zero baseline, `AND(I0, I1)` on input `[1, 1]` gives:

```python
base_value = 0
# Output of AND(0, 0) on the all-zero baseline input.

output_value = 1
# Output of AND(1, 1) on the current input.

values = [1 / 2, 1 / 2]
# I0 contributes 1/2.
# I1 contributes 1/2.

base_value + sum(values) == output_value
# 0 + 1/2 + 1/2 == 1
```

Both inputs are needed to turn the output on, so the local credit is split
equally.

`OR(I0, I1)` on input `[1, 1]` also gives:

```python
base_value = 0
# Output of OR(0, 0) on the all-zero baseline input.

output_value = 1
# Output of OR(1, 1) on the current input.

values = [1 / 2, 1 / 2]
# I0 contributes 1/2.
# I1 contributes 1/2.
```

Either input would be enough by itself, so the redundant positive effect is
split between them.

`AND(I0, I1)` on input `[1, 0]` gives:

```python
base_value = 0
# Output of AND(0, 0) on the all-zero baseline input.

output_value = 0
# Output of AND(1, 0) on the current input.

values = [0, 0]
# I0 changed from 0 to 1, but the target output stayed 0.
# I1 stayed at 0.
```

The first input changed, but the requested output did not change from the
baseline, so there is no output change to attribute.

`NOT(I0)` on input `[1]` gives:

```python
base_value = 1
# Output of NOT(0) on the all-zero baseline input.

output_value = 0
# Output of NOT(1) on the current input.

values = [-1]
# I0 contributes -1 because changing I0 from 0 to 1 turns the output off.

base_value + sum(values) == output_value
# 1 + (-1) == 0
```

The input change turns the output off, so the attribution is negative.

## API

```python
explain(circuit, inputs, output=0, *, baseline_inputs=None) -> ShapleyResult
```

`circuit` may be one of:

- `circuit_static_description.Circuit`
- circuit text
- a circuit file path

`baseline_inputs` is the reference sample. By default, it is the all-zero input.
You can also pass one boolean value for all inputs, or a sequence with the same
length as the circuit input count.

```python
shapley_values(circuit, inputs, output=0, *, baseline_inputs=None, as_float=False)
calculate_shapley_values(...)  # Alias for shapley_values.
```

Useful `ShapleyResult` fields:

- `values`: one attribution per input, represented exactly as `fractions.Fraction`
- `output_value`: output value for the current sample
- `base_value`: output value for the baseline sample
- `input_values`: normalized current sample inputs
- `baseline_input_values`: normalized baseline inputs

The result always satisfies:

```python
result.base_value + sum(result.values) == result.output_value
```

## Heatmap Visualization

You can fold a one-dimensional local Shapley vector into rows with `K` columns
and visualize it as a heatmap. This is useful when the circuit inputs originally
represent a grid, image, board, or any other fixed-width layout.

```python
from circuit_static_description import Circuit
from shapley_value_for_circuit import (
    explain,
    fold_shapley_values,
    save_shapley_heatmap,
    show_shapley_heatmap,
)

circuit = Circuit(
    6,  # Number of inputs.
    1,  # Number of outputs.
    outputs=["OR(AND(I0, I1), AND(I4, I5))"],
)

result = explain(circuit, inputs=[1, 1, 0, 0, 1, 1], output=0)

matrix = fold_shapley_values(result, columns=3)
# Fold the 6 input attributions into 2 rows and 3 columns:
# [
#   [phi_I0, phi_I1, phi_I2],
#   [phi_I3, phi_I4, phi_I5],
# ]

save_shapley_heatmap(
    result,
    columns=3,
    path="local_shapley_heatmap.png",
    title="Local Shapley values",
    annotate=True,
)
# Save the heatmap image to local_shapley_heatmap.png.

show_shapley_heatmap(result, columns=3)
# Open an interactive matplotlib window for direct viewing.
```

For lower-level control, use `plot_shapley_heatmap(...)`, which returns
`(fig, ax)` so you can further customize the matplotlib figure before saving or
showing it.

## Algorithm

This package computes circuit-local Shapley propagation. It does not enumerate
all input subsets and does not compute the exponential global Shapley value.

The algorithm is:

1. Each original input starts with its change from the baseline.
2. Each logic gate is explained by the exact Shapley values of its unary or
   binary local game.
3. Each gate-level attribution is propagated through the upstream attribution
   vectors until it reaches the original inputs.

Supported `circuit-static-description` gates:

- `AND`
- `OR`
- `NOT`
- `XOR`
- `NAND`
- `NOR`

The runtime is polynomial. If `n` is the input count and `g` is the number of
gates and variables reachable from the requested output, the dense worst case is
approximately `O(g * n)`, because each intermediate node may carry an attribution
vector over all original inputs. Sparse cases are usually smaller.
