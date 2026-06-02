"""Heatmap visualization helpers for local Shapley attribution vectors."""

from __future__ import annotations

import math
from fractions import Fraction
from os import PathLike
from pathlib import Path
from typing import Any, Sequence

from .core import LocalShapleyError, ShapleyResult

ShapleyVector = Sequence[int | float | Fraction] | ShapleyResult


def fold_shapley_values(
    values: ShapleyVector,
    columns: int,
    *,
    fill_value: int | float | Fraction = 0,
) -> tuple[tuple[int | float | Fraction, ...], ...]:
    """Fold a one-dimensional attribution vector into rows with fixed width."""

    if columns <= 0:
        raise LocalShapleyError(f"columns must be positive, got {columns}")

    vector = tuple(_extract_values(values))
    if not vector:
        raise LocalShapleyError("values must contain at least one attribution")

    rows = []
    for start in range(0, len(vector), columns):
        row = list(vector[start : start + columns])
        if len(row) < columns:
            row.extend(fill_value for _ in range(columns - len(row)))
        rows.append(tuple(row))
    return tuple(rows)


def plot_shapley_heatmap(
    values: ShapleyVector,
    columns: int,
    *,
    ax: Any | None = None,
    title: str | None = None,
    cmap: str = "coolwarm",
    center_zero: bool = True,
    colorbar: bool = True,
    annotate: bool = False,
    annotation_format: str = ".3g",
    fill_value: float = math.nan,
    pad_color: str = "#f2f2f2",
    aspect: str = "auto",
) -> tuple[Any, Any]:
    """Plot a folded local Shapley vector as a heatmap.

    ``matplotlib`` is imported lazily so the core attribution package remains
    usable without visualization dependencies.
    """

    plt = _import_pyplot()
    matrix = fold_shapley_values(values, columns, fill_value=fill_value)
    numeric_matrix = _to_float_matrix(matrix)
    finite_values = [
        value
        for row in numeric_matrix
        for value in row
        if math.isfinite(value)
    ]

    if not finite_values:
        raise LocalShapleyError("heatmap data does not contain any finite values")

    if ax is None:
        fig, ax = plt.subplots()
    else:
        fig = ax.figure

    vmin = vmax = None
    if center_zero:
        limit = max(abs(min(finite_values)), abs(max(finite_values)))
        limit = limit or 1.0
        vmin = -limit
        vmax = limit

    colormap = plt.get_cmap(cmap).copy()
    colormap.set_bad(color=pad_color)

    image = ax.imshow(
        numeric_matrix,
        cmap=colormap,
        vmin=vmin,
        vmax=vmax,
        aspect=aspect,
    )
    ax.set_xlabel(f"Folded column, K={columns}")
    ax.set_ylabel("Folded row")
    if title is not None:
        ax.set_title(title)

    if annotate:
        _annotate_cells(ax, numeric_matrix, annotation_format)

    if colorbar:
        fig.colorbar(image, ax=ax, label="Local Shapley value")

    fig.tight_layout()
    return fig, ax


def save_shapley_heatmap(
    values: ShapleyVector,
    columns: int,
    path: str | PathLike[str],
    *,
    dpi: int = 150,
    close: bool = True,
    **plot_kwargs: Any,
) -> Path:
    """Save a folded local Shapley heatmap image and return its path."""

    plt = _import_pyplot()
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig, _ = plot_shapley_heatmap(values, columns, **plot_kwargs)
    fig.savefig(output_path, dpi=dpi, bbox_inches="tight")
    if close:
        plt.close(fig)
    return output_path


def show_shapley_heatmap(
    values: ShapleyVector,
    columns: int,
    **plot_kwargs: Any,
) -> tuple[Any, Any]:
    """Display a folded local Shapley heatmap with ``matplotlib.pyplot.show``."""

    plt = _import_pyplot()
    fig, ax = plot_shapley_heatmap(values, columns, **plot_kwargs)
    plt.show()
    return fig, ax


def _extract_values(values: ShapleyVector) -> Sequence[int | float | Fraction]:
    if isinstance(values, ShapleyResult):
        return values.values
    return values


def _to_float_matrix(
    matrix: Sequence[Sequence[int | float | Fraction]],
) -> list[list[float]]:
    return [[float(value) for value in row] for row in matrix]


def _annotate_cells(
    ax: Any,
    matrix: Sequence[Sequence[float]],
    annotation_format: str,
) -> None:
    for row_index, row in enumerate(matrix):
        for column_index, value in enumerate(row):
            if not math.isfinite(value):
                continue
            ax.text(
                column_index,
                row_index,
                format(value, annotation_format),
                ha="center",
                va="center",
                fontsize=8,
            )


def _import_pyplot() -> Any:
    try:
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as exc:
        raise LocalShapleyError(
            "matplotlib is required for heatmap visualization; "
            "install shapley-value-for-circuit[viz]"
        ) from exc
    return plt
