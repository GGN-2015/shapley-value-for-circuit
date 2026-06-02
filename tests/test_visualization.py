from fractions import Fraction

import pytest
from circuit_static_description import Circuit

from shapley_value_for_circuit import (
    LocalShapleyError,
    explain,
    fold_shapley_values,
    plot_shapley_heatmap,
    save_shapley_heatmap,
    show_shapley_heatmap,
)


def test_fold_shapley_values_uses_fixed_column_count():
    values = [Fraction(1, 2), Fraction(-1, 2), Fraction(0)]

    matrix = fold_shapley_values(values, columns=2)

    assert matrix == (
        (Fraction(1, 2), Fraction(-1, 2)),
        (Fraction(0), 0),
    )


def test_fold_shapley_values_accepts_result_objects():
    circuit = Circuit(2, 1, outputs=["AND(I0, I1)"])
    result = explain(circuit, [1, 1])

    matrix = fold_shapley_values(result, columns=1)

    assert matrix == ((Fraction(1, 2),), (Fraction(1, 2),))


def test_fold_shapley_values_rejects_invalid_columns():
    with pytest.raises(LocalShapleyError):
        fold_shapley_values([1, 2], columns=0)


def test_save_shapley_heatmap_writes_image(tmp_path):
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg", force=True)

    output_path = tmp_path / "heatmap.png"

    saved_path = save_shapley_heatmap(
        [Fraction(1, 2), Fraction(-1, 2), Fraction(0)],
        columns=2,
        path=output_path,
        title="Local Shapley heatmap",
        annotate=True,
    )

    assert saved_path == output_path
    assert output_path.exists()
    assert output_path.stat().st_size > 0


def test_plot_shapley_heatmap_returns_figure_and_axes():
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg", force=True)

    fig, ax = plot_shapley_heatmap([1, -1, 0], columns=2)

    assert fig is ax.figure


def test_show_shapley_heatmap_calls_pyplot_show(monkeypatch):
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    called = {"show": False}

    def fake_show():
        called["show"] = True

    monkeypatch.setattr(plt, "show", fake_show)

    fig, ax = show_shapley_heatmap([1, -1, 0], columns=2)

    assert called["show"] is True
    assert fig is ax.figure
