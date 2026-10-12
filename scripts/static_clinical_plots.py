import os
import re
import textwrap

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np


PALETTE = [
    "#0F766E", "#F59E0B", "#14B8A6", "#EA580C", "#22C55E", "#2563EB",
    "#D97706", "#8B5CF6", "#F43F5E", "#059669", "#0891B2", "#A855F7",
    "#F97316", "#84CC16", "#06B6D4", "#F43F5E",
]


def _slugify(value):
    return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_") or "clinical_association"


def _trace_color(trace, idx):
    marker = trace.get("marker", {}) or {}
    color = marker.get("color")
    if isinstance(color, list):
        color = color[0] if color else None
    return color or PALETTE[idx % len(PALETTE)]


def _wrap(value, width=18):
    text = str(value)
    if len(text) <= width:
        return text
    return "\n".join(textwrap.wrap(text, width=width, break_long_words=True, break_on_hyphens=True)[:3])


def _numeric_values(values):
    numeric = []
    for value in values or []:
        try:
            numeric_value = float(value)
        except Exception:
            continue
        if np.isfinite(numeric_value):
            numeric.append(numeric_value)
    return numeric


def _figure_title(ax, clinical_var, subtitle=None):
    ax.set_title(str(clinical_var), loc="left", fontsize=15, fontweight="bold", pad=18)
    if not subtitle:
        return
    ax.text(
        0,
        1.015,
        subtitle,
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=9,
        color="#64748b",
    )


def _save_figure(fig, path, dpi=300):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def _categorical_static_plot(item, path, dpi=300):
    traces = item.get("plot_traces") or []
    clinical_var = str(item.get("clinical_var", "Clinical variable"))
    if not traces:
        return None

    categories = []
    for trace in traces:
        for value in trace.get("x", []) or []:
            label = str(value)
            if label not in categories:
                categories.append(label)
    if not categories:
        return None

    trace_maps = []
    labels = []
    colors = []
    for idx, trace in enumerate(traces):
        xs = [str(value) for value in (trace.get("x", []) or [])]
        ys = _numeric_values(trace.get("y", []) or [])
        mapping = {x: float(y) for x, y in zip(xs, ys)}
        trace_maps.append(mapping)
        labels.append(str(trace.get("name", f"Group {idx + 1}")))
        colors.append(_trace_color(trace, idx))

    trace_count = len(traces)
    category_count = len(categories)
    legend_cols = max(1, min(5, int(np.ceil(trace_count / 28)))) if trace_count > 18 else 1
    legend_rows = int(np.ceil(trace_count / legend_cols))
    fig_width = max(9.5, category_count * 1.55 + legend_cols * 3.4)
    fig_height = max(6.2, 4.6 + min(9.0, legend_rows * 0.22))

    fig, ax = plt.subplots(figsize=(fig_width, fig_height), constrained_layout=False)
    x = np.arange(category_count)
    bottom = np.zeros(category_count, dtype=float)

    for label, color, mapping in zip(labels, colors, trace_maps):
        values = np.array([mapping.get(category, 0.0) for category in categories], dtype=float)
        ax.bar(x, values, bottom=bottom, label=label, color=color, width=0.68, edgecolor="white", linewidth=0.7)
        bottom += values

    _figure_title(ax, clinical_var)
    ax.set_ylabel("Sample count")
    ax.set_xlabel("Subtype")
    ax.set_xticks(x)
    ax.set_xticklabels([_wrap(category, 16) for category in categories], rotation=0, ha="center", fontsize=8)
    ax.grid(axis="y", color="#e2e8f0", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    legend = ax.legend(
        title=str(item.get("clinical_var", "Legend")),
        loc="upper left",
        bbox_to_anchor=(1.01, 1.0),
        borderaxespad=0,
        frameon=False,
        ncol=legend_cols,
        fontsize=7.5 if trace_count > 24 else 8.5,
        title_fontsize=9,
        handlelength=1.1,
        handletextpad=0.45,
        columnspacing=0.9,
        labelspacing=0.45,
    )
    for text in legend.get_texts():
        text.set_text(_wrap(text.get_text(), 28))

    fig.subplots_adjust(left=0.08, right=max(0.58, 0.82 - legend_cols * 0.05), top=0.86, bottom=0.15)
    return _save_figure(fig, path, dpi=dpi)


def _continuous_static_plot(item, path, dpi=300):
    traces = item.get("plot_traces") or []
    clinical_var = str(item.get("clinical_var", "Clinical variable"))
    groups = []
    for idx, trace in enumerate(traces):
        values = trace.get("y") if trace.get("orientation") != "h" else trace.get("x")
        numeric = _numeric_values(values)
        if numeric:
            groups.append((str(trace.get("name", f"Group {idx + 1}")), numeric, _trace_color(trace, idx)))
    if not groups:
        return None

    group_count = len(groups)
    fig_width = max(8.5, group_count * 1.25)
    fig_height = 6.5
    fig, ax = plt.subplots(figsize=(fig_width, fig_height), constrained_layout=False)

    data = [values for _, values, _ in groups]
    colors = [color for _, _, color in groups]
    positions = np.arange(1, group_count + 1)
    box = ax.boxplot(
        data,
        positions=positions,
        widths=0.52,
        patch_artist=True,
        showfliers=True,
        medianprops={"color": "#0f172a", "linewidth": 1.4},
        boxprops={"linewidth": 1.2},
        whiskerprops={"linewidth": 1.1},
        capprops={"linewidth": 1.1},
        flierprops={"marker": "o", "markersize": 3, "alpha": 0.55},
    )
    for patch, color in zip(box["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.38)
        patch.set_edgecolor(color)
    for key in ("whiskers", "caps"):
        for idx, artist in enumerate(box[key]):
            artist.set_color(colors[idx // 2])

    rng = np.random.default_rng(42)
    for pos, (_, values, color) in zip(positions, groups):
        jitter = rng.normal(0, 0.035, size=len(values))
        ax.scatter(np.full(len(values), pos) + jitter, values, s=13, color=color, alpha=0.72, linewidths=0)

    _figure_title(ax, clinical_var)
    ax.set_ylabel(str(clinical_var))
    ax.set_xlabel("Subtype")
    ax.set_xticks(positions)
    ax.set_xticklabels([_wrap(name, 14) for name, _, _ in groups], rotation=0, ha="center", fontsize=8)
    ax.grid(axis="y", color="#e2e8f0", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.subplots_adjust(left=0.08, right=0.98, top=0.84, bottom=0.18)
    return _save_figure(fig, path, dpi=dpi)


def save_static_clinical_plot(item, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    filename = f"{_slugify(item.get('clinical_var', 'clinical_association'))}_static_data.png"
    path = os.path.join(output_dir, filename)
    if item.get("analysis_kind") == "continuous":
        return _continuous_static_plot(item, path)
    return _categorical_static_plot(item, path)


def generate_static_clinical_plots_from_summary(summary_path, output_dir=None):
    import json

    with open(summary_path, "r") as f:
        summary = json.load(f) or []
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(summary_path), "img")
    os.makedirs(output_dir, exist_ok=True)
    clinical_dir = os.path.dirname(summary_path)
    for filename in os.listdir(clinical_dir):
        if re.match(r".*_static_300dpi\.(png|csv)$", filename):
            try:
                os.remove(os.path.join(clinical_dir, filename))
            except Exception:
                pass

    paths = []
    for item in summary:
        path = save_static_clinical_plot(item, output_dir)
        if path:
            item.pop("static_image_300dpi", None)
            item.pop("static_image_source", None)
            item["data_static_image"] = os.path.join("img", os.path.basename(path))
            paths.append(path)

    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    return paths


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate static clinical association PNG plots from a summary JSON file.")
    parser.add_argument("summary_path")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    for path in generate_static_clinical_plots_from_summary(args.summary_path, args.out):
        print(path)
