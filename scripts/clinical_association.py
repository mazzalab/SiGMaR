import json
import os
import re

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from scipy.stats import chi2_contingency, fisher_exact, f_oneway, kruskal, mannwhitneyu, norm, rankdata, shapiro, ttest_ind
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

from layouts.layout_results import SUBTYPE_PALETTE, _build_subtype_color_map

try:
    from scipy.stats import random_table
except Exception:
    random_table = None

from scripts.function import read_table_preview
from scripts.static_clinical_plots import save_static_clinical_plot


DEFAULT_COLORS = [
    "#0F766E", "#F59E0B", "#14B8A6", "#EA580C", "#22C55E", "#2563EB",
    "#D97706", "#8B5CF6", "#F43F5E", "#059669", "#0891B2", "#A855F7",
]


def _safe_string(value):
    if pd.isna(value):
        return "Unknown"
    text = str(value).strip()
    return text if text else "Unknown"


def _normalize_sample_key(value):
    text = _safe_string(value)
    if text == "Unknown":
        return ""
    return "".join(ch for ch in text.lower() if ch.isalnum())


def _load_input_metadata(output_dir):
    metadata_path = os.path.join(output_dir, "input_metadata.json")
    if not os.path.exists(metadata_path):
        return {}
    try:
        with open(metadata_path, "r") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _load_clinical_association_metadata(output_dir):
    metadata_path = os.path.join(output_dir, "clinical_association", "clinical_association_metadata.json")
    if not os.path.exists(metadata_path):
        return {}
    try:
        with open(metadata_path, "r") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _select_clinical_sample_column(clinical_df, result_samples, preferred_column=None):
    if clinical_df.empty:
        raise ValueError("annotation.csv is empty.")

    result_key_set = {
        _normalize_sample_key(sample)
        for sample in result_samples
        if _normalize_sample_key(sample)
    }
    if not result_key_set:
        raise ValueError("dashboard_data.json does not contain usable sample identifiers.")

    preferred_column = str(preferred_column) if preferred_column else None
    best_column = None
    best_score = (-1, -1, -1)
    overlap_details = []

    for col in clinical_df.columns:
        normalized_values = {
            _normalize_sample_key(value)
            for value in clinical_df[col].tolist()
            if _normalize_sample_key(value)
        }
        overlap = len(normalized_values & result_key_set)
        normalized_name = str(col).strip().lower()
        name_bonus = 1 if ("sample" in normalized_name or normalized_name in {"id", "sampleid", "sample_id", "sample id"}) else 0
        preferred_bonus = 2 if preferred_column and str(col) == preferred_column else 0
        non_empty = len(normalized_values)
        score = (overlap, preferred_bonus + name_bonus, non_empty)
        overlap_details.append((str(col), overlap))
        if score > best_score:
            best_score = score
            best_column = str(col)

    if best_column is None or best_score[0] <= 0:
        details = ", ".join(f"{col}={overlap}" for col, overlap in overlap_details[:8])
        raise ValueError(
            "No overlapping samples between dashboard_data.json and annotation.csv. "
            f"Closest clinical columns checked: {details or 'none'}."
        )

    return best_column, best_score[0]


def load_study_frames(output_dir):
    dashboard_path = os.path.join(output_dir, "dashboard_data.json")
    clinical_path = os.path.join(output_dir, "annotation.csv")

    if not os.path.exists(dashboard_path) or not os.path.exists(clinical_path):
        return None, None

    with open(dashboard_path, "r") as f:
        dashboard_data = json.load(f)

    results_df = pd.json_normalize(dashboard_data)
    if "Samples" not in results_df.columns:
        raise ValueError("dashboard_data.json does not contain a Samples column.")
    results_df["Samples"] = results_df["Samples"].map(_safe_string)
    results_df["_sample_key"] = results_df["Samples"].map(_normalize_sample_key)

    clinical_df = read_table_preview(clinical_path, nrows=None)
    if clinical_df.empty:
        raise ValueError("annotation.csv is empty.")

    metadata = _load_input_metadata(output_dir)
    clinical_id_col, _ = _select_clinical_sample_column(
        clinical_df,
        results_df["Samples"].tolist(),
        preferred_column=metadata.get("clinical_sample_column"),
    )
    clinical_df = clinical_df.copy()
    clinical_df["_sample_key"] = clinical_df[clinical_id_col].map(_normalize_sample_key)
    clinical_df = clinical_df.loc[clinical_df["_sample_key"] != ""].drop_duplicates(subset=["_sample_key"], keep="first")

    merged = results_df.merge(clinical_df, on="_sample_key", how="inner", suffixes=("", "_clinical"))
    merged = merged.drop(columns=["_sample_key"], errors="ignore")
    clinical_df = clinical_df.drop(columns=["_sample_key"], errors="ignore")
    if merged.empty:
        raise ValueError("No overlapping samples between dashboard_data.json and annotation.csv.")

    return merged, clinical_df, clinical_id_col


def filter_by_agreement(df, use_all_samples=False, agreement_threshold=0.7):
    if use_all_samples or "confidence" not in df.columns:
        return df.copy()

    confidence = pd.to_numeric(df["confidence"], errors="coerce").fillna(0)
    return df.loc[confidence >= float(agreement_threshold)].copy()


def _ordered_categories(values):
    ordered = []
    seen = set()
    for value in values:
        label = _safe_string(value)
        if label not in seen:
            ordered.append(label)
            seen.add(label)
    if ordered and all(_is_numeric_label(label) for label in ordered):
        return sorted(ordered, key=_numeric_category_sort_key)
    return ordered


def _is_numeric_label(label):
    try:
        float(str(label).strip())
        return True
    except Exception:
        return False


def _numeric_category_sort_key(label):
    try:
        return (0, float(str(label).strip()))
    except Exception:
        return (1, str(label).strip().lower())


def _is_continuous_variable(series):
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return False
    unique_count = int(numeric.nunique())
    if unique_count >= 10:
        return True
    if pd.api.types.is_float_dtype(numeric.dtype) and unique_count >= 4:
        return True
    return False


def _bh_adjust_pvalues(pvalues):
    if not pvalues:
        return []
    ranked = sorted(enumerate(pvalues), key=lambda item: item[1])
    adjusted = [1.0] * len(pvalues)
    prev = 1.0
    n = len(pvalues)
    for rank, (idx, pval) in enumerate(reversed(ranked), start=1):
        q = min(prev, (pval * n) / (n - rank + 1))
        adjusted[idx] = q
        prev = q
    return adjusted


def _sort_pairwise_records_by_pvalue(records):
    def key(record):
        try:
            return (0, float(record.get("p_value")))
        except Exception:
            return (1, float("inf"))

    return sorted(records or [], key=key)


def _dunn_pairwise_records(work, clinical_var, subtype_order):
    ranked = work[["primary_subtype", clinical_var]].copy()
    ranked["_value"] = pd.to_numeric(ranked[clinical_var], errors="coerce")
    ranked = ranked[ranked["_value"].notna()].copy()
    if ranked.empty:
        return []

    values = ranked["_value"].to_numpy(dtype=float)
    ranks = rankdata(values, method="average")
    ranked["_rank"] = ranks
    n_total = len(ranked)
    if n_total < 2:
        return []

    _, tie_counts = np.unique(values, return_counts=True)
    tie_sum = float(np.sum(tie_counts ** 3 - tie_counts))
    variance_base = (n_total * (n_total + 1) / 12.0) - (tie_sum / (12.0 * max(n_total - 1, 1)))
    if variance_base <= 0:
        return []

    group_stats = {}
    for subtype in subtype_order:
        group = ranked.loc[ranked["primary_subtype"] == subtype]
        if group.empty:
            continue
        group_stats[subtype] = {
            "n": int(group.shape[0]),
            "mean_rank": float(group["_rank"].mean()),
            "median": float(group["_value"].median()),
        }

    pairwise_records = []
    available_subtypes = [subtype for subtype in subtype_order if subtype in group_stats]
    for i, subtype_a in enumerate(available_subtypes):
        for subtype_b in available_subtypes[i + 1:]:
            stats_a = group_stats[subtype_a]
            stats_b = group_stats[subtype_b]
            denom = np.sqrt(variance_base * ((1.0 / stats_a["n"]) + (1.0 / stats_b["n"])))
            if denom <= 0 or not np.isfinite(denom):
                continue
            z_value = (stats_a["mean_rank"] - stats_b["mean_rank"]) / denom
            p_pair = 2.0 * norm.sf(abs(z_value))
            pairwise_records.append(
                {
                    "subtype_a": subtype_a,
                    "subtype_b": subtype_b,
                    "statistic": float(z_value),
                    "p_value": float(p_pair),
                    "effect": float(stats_a["median"] - stats_b["median"]),
                    "effect_label": "Median diff",
                    "n_a": stats_a["n"],
                    "n_b": stats_b["n"],
                    "test": "Dunn test",
                }
            )

    return pairwise_records


def _slugify(text):
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")


def _load_font(size, bold=False):
    for candidate in (("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),):
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _text_box(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _image_to_bytes(image, fmt="PNG", dpi=300):
    buffer = BytesIO()
    save_kwargs = {"dpi": (dpi, dpi)}
    if fmt.upper() == "TIFF":
        save_kwargs["compression"] = "tiff_deflate"
    image.save(buffer, format=fmt.upper(), **save_kwargs)
    buffer.seek(0)
    return buffer.getvalue()


def _clinical_association_export_filename(clinical_var, export_format):
    slug = _slugify(clinical_var) or "clinical_association"
    return f"{slug}.{export_format.lower()}"


def _clinical_association_static_image_filename(clinical_var, dpi=150):
    slug = _slugify(clinical_var) or "clinical_association"
    return f"{slug}_static_{int(dpi)}dpi.png"


def _clinical_association_static_image_path(clinical_dir, clinical_var, dpi=150):
    return os.path.join(clinical_dir, _clinical_association_static_image_filename(clinical_var, dpi=dpi))


def _numeric_to_float_list(values):
    numeric = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    return numeric.astype(float).tolist()


def _build_study_subtype_color_map(df):
    if df is None or df.empty or "primary_subtype" not in df.columns:
        return {}
    labels = [value for value in df["primary_subtype"].tolist() if _safe_string(value)]
    return _build_subtype_color_map(labels)


def _recolor_continuous_trace(trace, idx, color_map):
    name = _safe_string(trace.get("name", f"Group {idx + 1}"))
    color = color_map.get(name, SUBTYPE_PALETTE[idx % len(SUBTYPE_PALETTE)])
    return color


def _clinical_association_static_image(item, dpi=300):
    figure_json = item.get("figure_json", {})
    plot_traces = item.get("plot_traces")
    analysis_kind = item.get("analysis_kind", "categorical")
    clinical_var = str(item.get("clinical_var", "Unknown"))
    title = clinical_var

    data = plot_traces if isinstance(plot_traces, list) and plot_traces else (
        figure_json.get("data", []) if isinstance(figure_json, dict) else []
    )
    trace_count = len(data)
    category_count = 0
    if analysis_kind == "categorical":
        categories = []
        for trace in data:
            for value in (trace.get("x", []) or []):
                label = str(value)
                if label not in categories:
                    categories.append(label)
        category_count = len(categories)

    width = max(1500, int((180 * max(category_count, 1) + 520) * (dpi / 300)))
    height = max(1100, int((300 + 40 * max(trace_count, 1)) * (dpi / 300)))
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    body_font = _load_font(int(20 * (dpi / 300)))
    small_font = _load_font(int(16 * (dpi / 300)))
    tiny_font = _load_font(int(14 * (dpi / 300)))
    scale = dpi / 300.0
    pad = int(80 * scale)

    if not data:
        draw.text((pad, int(150 * scale)), "No plot data available", font=body_font, fill="#64748b")
        return img

    plot_x0 = pad
    plot_y0 = int(120 * scale)
    plot_x1 = width - int(320 * scale)
    plot_y1 = height - int(150 * scale)
    legend_x = width - int(250 * scale)
    legend_y = int(160 * scale)

    def _trace_color(trace, idx):
        marker = trace.get("marker", {}) or {}
        color = marker.get("color")
        if isinstance(color, list) and color:
            color = color[0]
        if analysis_kind == "continuous" and color is None:
            name = _safe_string(trace.get("name", f"Group {idx + 1}"))
            color = continuous_color_map.get(name)
        if not color:
            color = SUBTYPE_PALETTE[idx % len(SUBTYPE_PALETTE)]
        return color

    def _hex_to_rgb(hex_color):
        value = str(hex_color).lstrip("#")
        if len(value) != 6:
            return (59, 130, 246)
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))

    if analysis_kind == "continuous":
        # Determine orientation from the first trace.
        first_trace = data[0]
        is_horizontal = bool(first_trace.get("orientation") == "h" or first_trace.get("x"))
        trace_names = []
        for trace in data:
            name = _safe_string(trace.get("name"))
            if name not in trace_names:
                trace_names.append(name)
        continuous_color_map = _build_subtype_color_map(trace_names)
        groups = []
        for idx, trace in enumerate(data):
            name = str(trace.get("name", f"Group {idx + 1}"))
            values = _numeric_to_float_list(trace.get("y" if not is_horizontal else "x", []) or [])
            if not values:
                continue
            groups.append((name, values, _recolor_continuous_trace(trace, idx, continuous_color_map)))

        if not groups:
            draw.text((plot_x0, plot_y0), "No values available for export", font=body_font, fill="#64748b")
            return img

        all_values = [v for _, values, _ in groups for v in values]
        y_min = min(all_values)
        y_max = max(all_values)
        if y_min == y_max:
            y_min -= 1.0
            y_max += 1.0
        box_width = (plot_x1 - plot_x0) / max(len(groups), 1)
        axis_left = plot_x0 + int(10 * scale)
        axis_top = plot_y0
        axis_bottom = plot_y1 - int(80 * scale)
        axis_right = plot_x1
        draw.line((axis_left, axis_top, axis_left, axis_bottom), fill="#94a3b8", width=2)
        draw.line((axis_left, axis_bottom, axis_right, axis_bottom), fill="#94a3b8", width=2)
        ticks = 5
        for i in range(ticks + 1):
            frac = i / ticks
            value = y_min + (y_max - y_min) * frac
            y = axis_bottom - (axis_bottom - axis_top) * frac
            draw.line((axis_left - 6, y, axis_left, y), fill="#94a3b8", width=2)
            label = f"{value:.1f}" if abs(y_max - y_min) < 100 else f"{value:.0f}"
            tw, th = _text_box(draw, label, tiny_font)
            draw.text((axis_left - tw - 10, y - th / 2), label, font=tiny_font, fill="#64748b")

        def map_y(value):
            return axis_bottom - (float(value) - y_min) / (y_max - y_min) * (axis_bottom - axis_top)

        for idx, (name, values, color) in enumerate(groups):
            x_center = plot_x0 + int((idx + 0.5) * box_width)
            sorted_vals = sorted(values)
            q1 = float(np.percentile(sorted_vals, 25))
            q2 = float(np.percentile(sorted_vals, 50))
            q3 = float(np.percentile(sorted_vals, 75))
            iqr = q3 - q1
            lower = max(min(sorted_vals), q1 - 1.5 * iqr)
            upper = min(max(sorted_vals), q3 + 1.5 * iqr)
            c = _hex_to_rgb(color)
            box_fill = tuple(min(255, int(v + 70)) for v in c)
            box_left = x_center - int(28 * scale)
            box_right = x_center + int(28 * scale)
            draw.line((x_center, map_y(lower), x_center, map_y(q1)), fill=color, width=3)
            draw.line((x_center, map_y(q3), x_center, map_y(upper)), fill=color, width=3)
            draw.rectangle((box_left, map_y(q3), box_right, map_y(q1)), fill=box_fill, outline=color, width=3)
            draw.line((box_left, map_y(q2), box_right, map_y(q2)), fill="#0f172a", width=2)
            draw.line((box_left, map_y(lower), box_right, map_y(lower)), fill=color, width=2)
            draw.line((box_left, map_y(upper), box_right, map_y(upper)), fill=color, width=2)
            for value in values:
                jitter = (hash((name, value)) % 11 - 5) * int(2 * scale)
                x = x_center + jitter
                y = map_y(value)
                draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=color, outline=color)
            tw, th = _text_box(draw, name, small_font)
            draw.text((x_center - tw / 2, axis_bottom + int(14 * scale)), name, font=small_font, fill="#334155")
    else:
        traces = data
        category_labels = []
        for trace in traces:
            xs = trace.get("x", []) or []
            for x in xs:
                x_str = str(x)
                if x_str not in category_labels:
                    category_labels.append(x_str)
        if not category_labels:
            draw.text((plot_x0, plot_y0), "No categories available for export", font=body_font, fill="#64748b")
            return img

        bar_width = (plot_x1 - plot_x0) / max(len(category_labels), 1)
        max_total = 0
        counts_by_trace = []
        for idx, trace in enumerate(traces):
            ys = [float(v) for v in (trace.get("y", []) or []) if v is not None]
            xs = [str(v) for v in (trace.get("x", []) or [])]
            mapping = {x: float(y) for x, y in zip(xs, ys)}
            counts_by_trace.append((str(trace.get("name", f"Group {idx + 1}")), mapping, _trace_color(trace, idx)))
            for x in category_labels:
                max_total = max(max_total, mapping.get(x, 0))
        axis_left = plot_x0 + int(10 * scale)
        axis_top = plot_y0
        axis_bottom = plot_y1 - int(80 * scale)
        axis_right = plot_x1
        draw.line((axis_left, axis_top, axis_left, axis_bottom), fill="#94a3b8", width=2)
        draw.line((axis_left, axis_bottom, axis_right, axis_bottom), fill="#94a3b8", width=2)
        if max_total <= 0:
            max_total = 1

        def map_y(value):
            return axis_bottom - (float(value) / max_total) * (axis_bottom - axis_top)

        for idx, label in enumerate(category_labels):
            x0 = plot_x0 + idx * bar_width + int(12 * scale)
            x1 = plot_x0 + (idx + 1) * bar_width - int(12 * scale)
            center_x = (x0 + x1) / 2
            cumulative = 0.0
            for trace_idx, (name, mapping, color) in enumerate(counts_by_trace):
                val = mapping.get(label, 0)
                if val <= 0:
                    continue
                top_value = cumulative + float(val)
                bottom_value = cumulative
                top = map_y(top_value)
                bottom = map_y(bottom_value)
                rect_top = min(top, bottom)
                rect_bottom = max(top, bottom)
                draw.rectangle((x0, rect_top, x1, rect_bottom), fill=color, outline="white")
                cumulative = top_value
            tw, th = _text_box(draw, label, small_font)
            draw.text((center_x - tw / 2, axis_bottom + int(14 * scale)), label, font=small_font, fill="#334155")

    # Legend
    legend_title = "Subtype colors" if analysis_kind == "continuous" else "Legend"
    draw.text((legend_x, int(120 * scale)), legend_title, font=body_font, fill="#0f172a")
    if analysis_kind == "continuous":
        for idx, trace in enumerate(data):
            name = str(trace.get("name", f"Group {idx + 1}"))
            color = _trace_color(trace, idx)
            y = legend_y + idx * int(38 * scale)
            draw.rounded_rectangle((legend_x, y, legend_x + int(24 * scale), y + int(24 * scale)), radius=int(6 * scale), fill=color)
            draw.text((legend_x + int(34 * scale), y + int(2 * scale)), name, font=small_font, fill="#334155")
    else:
        for idx, trace in enumerate(data):
            name = str(trace.get("name", f"Group {idx + 1}"))
            color = _trace_color(trace, idx)
            y = legend_y + idx * int(38 * scale)
            draw.rounded_rectangle((legend_x, y, legend_x + int(24 * scale), y + int(24 * scale)), radius=int(6 * scale), fill=color)
            draw.text((legend_x + int(34 * scale), y + int(2 * scale)), name, font=small_font, fill="#334155")

    return img


def _clinical_association_plotly_figure(item, strip_title=False):
    figure_json = item.get("figure_json", {})
    try:
        fig = go.Figure(figure_json if isinstance(figure_json, dict) else {})
    except Exception:
        fig = go.Figure()

    if strip_title:
        try:
            fig.update_layout(title_text=None)
        except Exception:
            pass
    return fig


def _clinical_association_export_dimensions(item, dpi=300):
    figure_json = item.get("figure_json", {})
    data = figure_json.get("data", []) if isinstance(figure_json, dict) else []
    analysis_kind = item.get("analysis_kind", "categorical")
    trace_count = len(data)
    category_count = 0

    if analysis_kind == "categorical":
        categories = []
        for trace in data:
            for value in (trace.get("x", []) or []):
                label = str(value)
                if label not in categories:
                    categories.append(label)
        category_count = len(categories)

    width = max(1600, 180 * max(category_count, 1) + 520)
    height = max(1100, 300 + 34 * max(trace_count, 1))
    if int(dpi) >= 300:
        width = min(width, 2600)
        height = min(height, 2200)
    return int(width), int(height)


def _clinical_association_plotly_image_bytes(item, export_format="png", dpi=300, strip_title=False):
    try:
        fig = _clinical_association_plotly_figure(item, strip_title=strip_title)
        width, height = _clinical_association_export_dimensions(item, dpi=dpi)
        fig.update_layout(
            width=width,
            height=height,
            margin=dict(l=80, r=300, t=90 if not strip_title else 45, b=120),
            legend=dict(
                orientation="v",
                yanchor="top",
                y=1,
                xanchor="left",
                x=1.02,
                traceorder="normal",
            ),
        )
        fig.update_xaxes(automargin=True)
        fig.update_yaxes(automargin=True)
        scale = 1 if int(dpi) <= 150 else 2
        image_format = "png" if export_format.lower() == "tiff" else export_format.lower()
        return fig.to_image(format=image_format, width=width, height=height, scale=scale)
    except Exception:
        return None


def build_clinical_association_export_bytes(item, export_format="png", dpi=300, static_image_path=None):
    fmt = export_format.lower()
    if static_image_path and not os.path.exists(static_image_path):
        try:
            save_static_clinical_plot(item, os.path.dirname(static_image_path))
        except Exception:
            pass
    # save_static_clinical_plot renders at one fixed, dpi-independent resolution
    # (its historical field name was static_image_300dpi), so this shortcut is only
    # correct when the caller actually asked for that nominal 300 dpi - otherwise it
    # silently ignored the requested dpi (150 dpi downloads returned the 300 dpi file).
    # A different dpi falls through to the live Plotly render below, which does scale
    # with dpi, and that render's own dpi-aware fallback (_clinical_association_static_image)
    # if the live render fails.
    if static_image_path and os.path.exists(static_image_path) and int(dpi) == 300:
        with open(static_image_path, "rb") as f:
            static_payload = f.read()
        if fmt == "png":
            return static_payload
        if fmt == "tiff":
            try:
                image = Image.open(BytesIO(static_payload)).convert("RGB")
                return _image_to_bytes(image, "TIFF", dpi=dpi)
            except Exception:
                pass

    if fmt in ("png", "tiff"):
        payload = _clinical_association_plotly_image_bytes(item, export_format=fmt, dpi=dpi, strip_title=False)
        if payload is None:
            image = _clinical_association_static_image(item, dpi=dpi)
            payload = _image_to_bytes(image, fmt.upper(), dpi=dpi)
        if fmt == "png" and static_image_path:
            # Only persist to the shared cache file when this render actually is the
            # canonical 300 dpi version - caching a 150 dpi render here would make the
            # next dpi=300 request (and the dpi==300 shortcut above) silently serve it.
            if int(dpi) == 300:
                try:
                    os.makedirs(os.path.dirname(static_image_path), exist_ok=True)
                    with open(static_image_path, "wb") as f:
                        f.write(payload)
                except Exception:
                    pass
            return payload
        if fmt == "tiff":
            try:
                image = Image.open(BytesIO(payload)).convert("RGB")
                return _image_to_bytes(image, "TIFF", dpi=dpi)
            except Exception:
                image = _clinical_association_static_image(item, dpi=dpi)
                return _image_to_bytes(image, "TIFF", dpi=dpi)
        return payload
    if fmt == "pdf":
        try:
            from reportlab.lib.pagesizes import landscape, letter
            from reportlab.platypus import Image as RLImage, SimpleDocTemplate
        except Exception as exc:
            raise RuntimeError(f"PDF export dependencies are not available: {exc}") from exc

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), rightMargin=28, leftMargin=28, topMargin=28, bottomMargin=28)
        # Just the chart, same as the PNG/TIFF downloads (strip_title=False keeps its own
        # in-image title, same as those), wrapped in a PDF page - no added title/stats text.
        payload = _clinical_association_plotly_image_bytes(item, export_format="png", dpi=dpi, strip_title=False)
        if payload is None:
            image = _clinical_association_static_image(item, dpi=dpi)
            payload = _image_to_bytes(image, "PNG", dpi=dpi)
        img_buffer = BytesIO(payload)
        chart = RLImage(img_buffer)
        max_width = doc.width
        max_height = doc.height
        scale = min(max_width / chart.imageWidth, max_height / chart.imageHeight)
        chart.drawWidth = chart.imageWidth * scale
        chart.drawHeight = chart.imageHeight * scale
        doc.build([chart])
        pdf_bytes = buffer.getvalue()
        buffer.close()
        return pdf_bytes
    raise ValueError(f"Unsupported export format: {export_format}")


def _needs_exact_categorical_test(contingency):
    if contingency.shape[0] <= 2 and contingency.shape[1] <= 2:
        return False
    expected = chi2_contingency(contingency.values)[3]
    expected_min = float(np.min(expected)) if expected.size else 0.0
    observed_min = float(np.min(contingency.values)) if contingency.size else 0.0
    return expected_min < 5.0 or observed_min < 5.0


def _monte_carlo_rxc_pvalue(contingency, observed_stat, n_iter=5000, seed=12345):
    if random_table is None:
        return None

    row_margins = contingency.sum(axis=1).to_numpy(dtype=int)
    col_margins = contingency.sum(axis=0).to_numpy(dtype=int)
    if row_margins.sum() <= 0 or col_margins.sum() <= 0:
        return None

    rng = np.random.default_rng(seed)
    ge_count = 0
    valid = 0
    for _ in range(int(n_iter)):
        try:
            sample = random_table.rvs(row_margins, col_margins, random_state=rng)
        except Exception:
            return None
        sample = np.asarray(sample)
        try:
            stat = chi2_contingency(sample, correction=False)[0]
        except Exception:
            continue
        valid += 1
        if stat >= observed_stat - 1e-12:
            ge_count += 1

    if valid == 0:
        return None
    return (ge_count + 1) / (valid + 1)


def _compute_categorical_statistics(df, clinical_var):
    if clinical_var not in df.columns:
        raise ValueError(f"Clinical variable '{clinical_var}' not found.")
    if "primary_subtype" not in df.columns:
        raise ValueError("primary_subtype column not found in merged data.")

    work = df[["primary_subtype", clinical_var]].copy()
    work["primary_subtype"] = work["primary_subtype"].map(_safe_string)
    work[clinical_var] = work[clinical_var].map(_safe_string)
    work = work[(work["primary_subtype"] != "") & (work[clinical_var] != "")]

    if work.empty:
        raise ValueError(
            f"No clinical association data available for '{clinical_var}' after applying the current filters."
        )

    clinical_levels = _ordered_categories(work[clinical_var].tolist())
    subtype_levels = _ordered_categories(work["primary_subtype"].tolist())
    contingency = pd.crosstab(
        pd.Categorical(work[clinical_var], categories=clinical_levels, ordered=True),
        pd.Categorical(work["primary_subtype"], categories=subtype_levels, ordered=True),
        dropna=False,
    ).reindex(index=clinical_levels, columns=subtype_levels, fill_value=0)
    if contingency.empty or int(contingency.to_numpy().sum()) == 0:
        raise ValueError(
            f"No clinical association data available for '{clinical_var}' after applying the current filters."
        )

    total_samples = int(contingency.to_numpy().sum())
    rows, cols = contingency.shape
    if rows < 2 or cols < 2:
        raise ValueError(
            f"Not enough categories to test association for '{clinical_var}'. "
            "At least two clinical levels and two subtype levels are required after filtering."
        )

    chi2, chi_p_value, dof, expected = chi2_contingency(contingency.values, correction=False)
    exact_p_value = None
    method = "Chi-square"
    statistic_label = "Chi-square"
    statistic_value = float(chi2)
    degrees_freedom = int(dof)

    if rows == 2 and cols == 2:
        odds_ratio, p_value = fisher_exact(contingency.values)
        method = "Fisher exact"
        statistic_label = "Odds ratio"
        statistic_value = float(odds_ratio)
        degrees_freedom = None
    else:
        p_value = chi_p_value
        if _needs_exact_categorical_test(contingency):
            exact_p_value = _monte_carlo_rxc_pvalue(contingency, chi2, n_iter=5000)
        if exact_p_value is not None:
            p_value = exact_p_value
            method = "Monte Carlo exact (5,000 tables)"

    expected_df = pd.DataFrame(expected, index=contingency.index, columns=contingency.columns)
    # Adjusted (Haberman) standardized residuals: (O - E) / sqrt(E (1 - r/N)(1 - c/N)).
    # These are approximately N(0,1), so the 1.96 cut-off below is valid; plain
    # Pearson residuals (O - E)/sqrt(E) are not.
    row_frac = contingency.sum(axis=1) / total_samples
    col_frac = contingency.sum(axis=0) / total_samples
    adj_denom = expected_df.mul(1.0 - row_frac, axis=0).mul(1.0 - col_frac, axis=1).pow(0.5)
    residuals = (contingency - expected_df) / adj_denom.replace(0, np.nan)
    residuals = residuals.fillna(0.0)
    residual_records = []
    for row_label in contingency.index:
        for col_label in contingency.columns:
            residual = float(residuals.loc[row_label, col_label])
            observed = int(contingency.loc[row_label, col_label])
            expected_value = float(expected_df.loc[row_label, col_label])
            residual_records.append(
                {
                    "clinical_level": _safe_string(row_label),
                    "subtype": _safe_string(col_label),
                    "residual": residual,
                    "observed": observed,
                    "expected": expected_value,
                }
            )

    significant_cells = [
        record for record in residual_records
        if record["residual"] >= 1.96
    ]
    significant_cells.sort(key=lambda item: item["residual"], reverse=True)

    top_positive = sorted(residual_records, key=lambda item: item["residual"], reverse=True)[:5]
    top_negative = sorted(residual_records, key=lambda item: item["residual"])[:5]
    top_enriched_subtype = top_positive[0]["subtype"] if top_positive else None

    pairwise_records = []
    clinical_levels = list(contingency.index)
    subtype_levels = list(contingency.columns)

    for subtype in subtype_levels:
        subtype_total = int(contingency[subtype].sum())
        other_total = total_samples - subtype_total
        if subtype_total <= 0 or other_total <= 0:
            continue
        for i, level_a in enumerate(clinical_levels):
            for level_b in clinical_levels[i + 1:]:
                a_subtype = int(contingency.loc[level_a, subtype])
                b_subtype = int(contingency.loc[level_b, subtype])
                a_other = int(contingency.loc[level_a].sum()) - a_subtype
                b_other = int(contingency.loc[level_b].sum()) - b_subtype
                if min(a_subtype, b_subtype, a_other, b_other) < 0:
                    continue
                try:
                    odds_ratio, p_val = fisher_exact([[a_subtype, a_other], [b_subtype, b_other]])
                except Exception:
                    continue
                pairwise_records.append(
                    {
                        "subtype": _safe_string(subtype),
                        "level_a": _safe_string(level_a),
                        "level_b": _safe_string(level_b),
                        "odds_ratio": float(odds_ratio),
                        "p_value": float(p_val),
                        "a_subtype": a_subtype,
                        "b_subtype": b_subtype,
                        "a_total": a_subtype + a_other,
                        "b_total": b_subtype + b_other,
                    }
                )

    q_values = _bh_adjust_pvalues([record["p_value"] for record in pairwise_records])
    for record, q_value in zip(pairwise_records, q_values):
        record["q_value"] = float(q_value)
    pairwise_records = _sort_pairwise_records_by_pvalue(pairwise_records)

    pairwise_significant = [
        record for record in pairwise_records
        if record["q_value"] < 0.05
    ]
    pairwise_significant.sort(key=lambda item: (item["q_value"], -abs(item["odds_ratio"] - 1.0)))

    return {
        "analysis_kind": "categorical",
        "method": method,
        "statistic_label": statistic_label,
        "statistic_value": statistic_value,
        "p_value": float(p_value),
        "degrees_freedom": degrees_freedom,
        "exact_p_value": exact_p_value,
        "total_samples": total_samples,
        "rows": rows,
        "cols": cols,
        "contingency": contingency,
        "clinical_levels": clinical_levels,
        "subtype_levels": subtype_levels,
        "significant_cells": significant_cells,
        "top_positive_cells": top_positive,
        "top_negative_cells": top_negative,
        "top_enriched_subtype": top_enriched_subtype,
        "pairwise_cells": pairwise_records,
        "pairwise_significant_cells": pairwise_significant,
    }



def _welch_anova(groups):
    """Welch's heteroscedastic one-way ANOVA (Welch 1951); falls back to the
    classical F test when a group has fewer than 2 values or zero variance."""
    k = len(groups)
    n = np.array([len(g) for g in groups], dtype=float)
    means = np.array([np.mean(g) for g in groups], dtype=float)
    var = np.array([np.var(g, ddof=1) if len(g) > 1 else np.nan for g in groups], dtype=float)
    if k < 2 or np.any(n < 2) or np.any(~np.isfinite(var)) or np.any(var <= 0):
        return f_oneway(*groups)
    w = n / var
    W = w.sum()
    grand = (w * means).sum() / W
    A = (w * (means - grand) ** 2).sum() / (k - 1)
    lam = ((1.0 - w / W) ** 2 / (n - 1)).sum()
    B = 2.0 * (k - 2) / (k ** 2 - 1) * lam
    F = A / (1.0 + B)
    df1 = k - 1
    df2 = (k ** 2 - 1) / (3.0 * lam)
    from scipy.stats import f as f_dist
    return float(F), float(f_dist.sf(F, df1, df2))

def _compute_continuous_statistics(df, clinical_var):
    if clinical_var not in df.columns:
        raise ValueError(f"Clinical variable '{clinical_var}' not found.")
    if "primary_subtype" not in df.columns:
        raise ValueError("primary_subtype column not found in merged data.")

    work = df[["primary_subtype", clinical_var]].copy()
    work["primary_subtype"] = work["primary_subtype"].map(_safe_string)
    work[clinical_var] = pd.to_numeric(work[clinical_var], errors="coerce")
    work = work[(work["primary_subtype"] != "") & work[clinical_var].notna()]

    if work.empty:
        raise ValueError(
            f"No clinical association data available for '{clinical_var}' after applying the current filters."
        )

    subtype_order = _ordered_categories(work["primary_subtype"].tolist())
    grouped_values = []
    median_records = []
    normality_records = []
    normality_passed = True
    for subtype in subtype_order:
        values = work.loc[work["primary_subtype"] == subtype, clinical_var].astype(float).tolist()
        if not values:
            continue
        grouped_values.append(values)
        shapiro_p = None
        if len(values) >= 3:
            try:
                _, shapiro_p = shapiro(values)
                shapiro_p = float(shapiro_p)
            except Exception:
                shapiro_p = None
        else:
            normality_passed = False
        if shapiro_p is None or shapiro_p <= 0.05:
            normality_passed = False
        normality_records.append(
            {
                "subtype": subtype,
                "n": len(values),
                "shapiro_p": shapiro_p if shapiro_p is not None else float("nan"),
            }
        )
        median_records.append(
            {
                "subtype": subtype,
                "median": float(pd.Series(values).median()),
                "mean": float(pd.Series(values).mean()),
                "std": float(pd.Series(values).std(ddof=1)) if len(values) > 1 else None,
                "n": len(values),
            }
        )

    if len(grouped_values) < 2:
        raise ValueError(
            f"Not enough subtype groups to test association for '{clinical_var}' after filtering."
        )

    if normality_passed:
        if len(grouped_values) == 2:
            stat, p_value = ttest_ind(grouped_values[0], grouped_values[1], equal_var=False, nan_policy="omit")
            method = "Welch t-test"
            statistic_label = "t"
            statistic_value = float(stat)
        else:
            stat, p_value = _welch_anova(grouped_values)
            method = "Welch ANOVA"
            statistic_label = "F"
            statistic_value = float(stat)
        pairwise_test_label = "Welch t-test"
        diff_label = "Mean diff"
        degrees_freedom = None
    else:
        if len(grouped_values) == 2:
            stat, p_value = mannwhitneyu(grouped_values[0], grouped_values[1], alternative="two-sided")
            method = "Mann-Whitney U"
            statistic_label = "U"
            statistic_value = float(stat)
            pairwise_test_label = "Mann-Whitney U"
        else:
            stat, p_value = kruskal(*grouped_values)
            method = "Kruskal-Wallis"
            statistic_label = "H"
            statistic_value = float(stat)
            pairwise_test_label = "Dunn test"
        diff_label = "Median diff"
        degrees_freedom = None

    median_records.sort(key=lambda item: item["median"], reverse=True)
    top_subtype = median_records[0]["subtype"] if median_records else None

    if not normality_passed and len(grouped_values) > 2:
        pairwise_records = _dunn_pairwise_records(work, clinical_var, subtype_order)
    else:
        pairwise_records = []
        for i, subtype_a in enumerate(subtype_order):
            values_a = work.loc[work["primary_subtype"] == subtype_a, clinical_var].astype(float).tolist()
            if not values_a:
                continue
            for subtype_b in subtype_order[i + 1:]:
                values_b = work.loc[work["primary_subtype"] == subtype_b, clinical_var].astype(float).tolist()
                if not values_b:
                    continue
                try:
                    if normality_passed:
                        stat_pair, p_pair = ttest_ind(values_a, values_b, equal_var=False, nan_policy="omit")
                        pair_effect = float(pd.Series(values_a).mean() - pd.Series(values_b).mean())
                    else:
                        stat_pair, p_pair = mannwhitneyu(values_a, values_b, alternative="two-sided")
                        pair_effect = float(pd.Series(values_a).median() - pd.Series(values_b).median())
                except Exception:
                    continue
                pairwise_records.append(
                    {
                        "subtype_a": subtype_a,
                        "subtype_b": subtype_b,
                        "statistic": float(stat_pair),
                        "p_value": float(p_pair),
                        "effect": float(pair_effect),
                        "effect_label": diff_label,
                        "n_a": len(values_a),
                        "n_b": len(values_b),
                        "test": pairwise_test_label,
                    }
                )

    q_values = _bh_adjust_pvalues([record["p_value"] for record in pairwise_records])
    for record, q_value in zip(pairwise_records, q_values):
        record["q_value"] = float(q_value)
    pairwise_records = _sort_pairwise_records_by_pvalue(pairwise_records)

    pairwise_significant = [
        record for record in pairwise_records
        if record["q_value"] < 0.05
    ]
    pairwise_significant.sort(key=lambda item: (item["q_value"], -abs(item["effect"])))

    return {
        "analysis_kind": "continuous",
        "method": method,
        "statistic_label": statistic_label,
        "statistic_value": statistic_value,
        "p_value": float(p_value),
        "degrees_freedom": degrees_freedom,
        "total_samples": int(work.shape[0]),
        "groups": len(grouped_values),
        "normality_passed": normality_passed,
        "normality_records": normality_records,
        "top_enriched_subtype": top_subtype,
        "median_records": median_records,
        "subtype_order": subtype_order,
        "pairwise_cells": pairwise_records,
        "pairwise_significant_cells": pairwise_significant,
    }


def build_categorical_figure(df, clinical_var, orientation="subtype_x", subtype_color_map=None):
    if clinical_var not in df.columns:
        raise ValueError(f"Clinical variable '{clinical_var}' not found.")
    if "primary_subtype" not in df.columns:
        raise ValueError("primary_subtype column not found in merged data.")

    work = df[["Samples", "primary_subtype", clinical_var]].copy()
    work["primary_subtype"] = work["primary_subtype"].map(_safe_string)
    work[clinical_var] = work[clinical_var].map(_safe_string)

    if orientation == "clinical_x":
        x_col = clinical_var
        stack_col = "primary_subtype"
        title = f"{clinical_var} by subtype"
        x_title = clinical_var
        legend_title = "Subtype"
    else:
        x_col = "primary_subtype"
        stack_col = clinical_var
        title = f"{clinical_var} across subtypes"
        x_title = "Subtype"
        legend_title = clinical_var

    x_order = _ordered_categories(work[x_col].tolist())
    stack_order = _ordered_categories(work[stack_col].tolist())
    if not x_order or not stack_order:
        raise ValueError(
            f"No clinical association data available for '{clinical_var}' after applying the current filters."
        )

    x_series = pd.Categorical(work[x_col], categories=x_order, ordered=True)
    stack_series = pd.Categorical(work[stack_col], categories=stack_order, ordered=True)
    pivot = pd.crosstab(x_series, stack_series, dropna=False).reindex(index=x_order, columns=stack_order, fill_value=0)

    if pivot.empty or int(pivot.to_numpy().sum()) == 0:
        raise ValueError(
            f"No clinical association data available for '{clinical_var}' after applying the current filters."
        )

    fig = go.Figure()
    color_map = subtype_color_map if stack_col == "primary_subtype" and subtype_color_map else (
        _build_subtype_color_map(stack_order) if stack_col == "primary_subtype" else None
    )
    for idx, stack_value in enumerate(stack_order):
        y_vals = [int(pivot.loc[x_value, stack_value]) for x_value in x_order]
        marker_color = color_map.get(stack_value, SUBTYPE_PALETTE[idx % len(SUBTYPE_PALETTE)]) if color_map else SUBTYPE_PALETTE[idx % len(SUBTYPE_PALETTE)]
        fig.add_trace(
            go.Bar(
                name=stack_value,
                x=x_order,
                y=y_vals,
                marker_color=marker_color,
                legendrank=idx + 1,
            )
        )

    fig.update_layout(
        barmode="stack",
        title=title,
        xaxis_title=x_title,
        yaxis_title="Sample count",
        legend_title_text=legend_title,
        legend_traceorder="normal",
        template="plotly_white",
        margin=dict(l=40, r=20, t=60, b=40),
        height=420,
    )
    return fig


def build_continuous_figure(df, clinical_var, orientation="subtype_x", subtype_color_map=None):
    if clinical_var not in df.columns:
        raise ValueError(f"Clinical variable '{clinical_var}' not found.")
    if "primary_subtype" not in df.columns:
        raise ValueError("primary_subtype column not found in merged data.")

    work = df[["primary_subtype", clinical_var]].copy()
    work["primary_subtype"] = work["primary_subtype"].map(_safe_string)
    work[clinical_var] = pd.to_numeric(work[clinical_var], errors="coerce")
    work = work[(work["primary_subtype"] != "") & work[clinical_var].notna()]
    if work.empty:
        raise ValueError(
            f"No clinical association data available for '{clinical_var}' after applying the current filters."
        )

    subtype_order = _ordered_categories(work["primary_subtype"].tolist())
    fig = go.Figure()
    color_map = subtype_color_map if subtype_color_map else _build_subtype_color_map(subtype_order)

    if orientation == "clinical_x":
        for idx, subtype in enumerate(subtype_order):
            values = work.loc[work["primary_subtype"] == subtype, clinical_var].astype(float).tolist()
            if not values:
                continue
            subtype_color = color_map.get(subtype, SUBTYPE_PALETTE[idx % len(SUBTYPE_PALETTE)])
            fig.add_trace(
                go.Box(
                    x=values,
                    y=[subtype] * len(values),
                    name=subtype,
                    orientation="h",
                    marker_color=subtype_color,
                    line_color=subtype_color,
                    fillcolor=subtype_color,
                    opacity=1.0,
                    boxmean=False,
                    boxpoints="outliers",
                )
            )
        fig.update_layout(
            title=f"{clinical_var} by subtype",
            xaxis_title=clinical_var,
            yaxis_title="Subtype",
        )
    else:
        for idx, subtype in enumerate(subtype_order):
            values = work.loc[work["primary_subtype"] == subtype, clinical_var].astype(float).tolist()
            if not values:
                continue
            subtype_color = color_map.get(subtype, SUBTYPE_PALETTE[idx % len(SUBTYPE_PALETTE)])
            fig.add_trace(
                go.Box(
                    y=values,
                    name=subtype,
                    orientation="v",
                    marker_color=subtype_color,
                    line_color=subtype_color,
                    fillcolor=subtype_color,
                    opacity=1.0,
                    boxmean=False,
                    boxpoints="outliers",
                )
            )
        fig.update_layout(
            title=f"{clinical_var} across subtypes",
            xaxis_title="Subtype",
            yaxis_title=clinical_var,
        )

    fig.update_layout(
        template="plotly_white",
        margin=dict(l=40, r=20, t=60, b=40),
        height=420,
        legend_title_text="Subtype",
        legend_traceorder="normal",
    )
    return fig


def persist_clinical_association_outputs(output_dir, figures, study_name=None, analysis_config=None):
    clinical_dir = os.path.join(output_dir, "clinical_association")
    clinical_img_dir = os.path.join(clinical_dir, "img")
    os.makedirs(clinical_dir, exist_ok=True)
    os.makedirs(clinical_img_dir, exist_ok=True)
    for filename in os.listdir(clinical_dir):
        if re.match(r".*_static_300dpi\.(png|csv)$", filename):
            try:
                os.remove(os.path.join(clinical_dir, filename))
            except Exception:
                pass

    summary = []
    summary_rows = []

    for clinical_var, fig, stats in figures:
        figure_json = fig.to_plotly_json()
        analysis_kind = stats.get("analysis_kind", "categorical")
        p_value = stats.get("p_value")
        method = stats.get("method", "n/a")
        stat_label = stats.get("statistic_label", "Statistic")
        stat_value = stats.get("statistic_value")
        top_subtype = stats.get("top_enriched_subtype")

        entry = {
            "clinical_var": clinical_var,
            "analysis_kind": analysis_kind,
            "method": method,
            # The real reason the statistical test couldn't be computed (e.g. "At least two
            # clinical levels and two subtype levels are required after filtering") - was
            # computed by _compute_*_statistics but discarded before this point, leaving every
            # display site with only a bare "n/a" and no explanation.
            "error": stats.get("error"),
            "statistic_label": stat_label,
            "statistic_value": stat_value,
            "p_value": p_value,
            "degrees_freedom": stats.get("degrees_freedom"),
            "total_samples": stats.get("total_samples"),
            "groups": stats.get("groups"),
            "rows": stats.get("rows"),
            "cols": stats.get("cols"),
            "top_enriched_subtype": top_subtype,
            "normality_passed": stats.get("normality_passed"),
            "orientation": stats.get("orientation"),
            "plot_traces": stats.get("plot_traces", []),
            "figure_json": figure_json,
            "significant_cells": stats.get("significant_cells", []),
            "top_positive_cells": stats.get("top_positive_cells", []),
            "pairwise_cells": stats.get("pairwise_cells", []),
            "pairwise_significant_cells": stats.get("pairwise_significant_cells", []),
            "median_records": stats.get("median_records", []),
            "normality_records": stats.get("normality_records", []),
        }
        summary.append(entry)
        summary_rows.append(
            {
                "clinical_var": clinical_var,
                "analysis_kind": analysis_kind,
                "method": method,
                "statistic_label": stat_label,
                "statistic_value": stat_value,
                "p_value": p_value,
                "total_samples": stats.get("total_samples"),
                "top_enriched_subtype": top_subtype,
                "error": stats.get("error"),
            }
        )

        slug = _slugify(clinical_var)
        pairwise_rows = []
        for cell in stats.get("pairwise_cells", []):
            if analysis_kind == "continuous":
                pairwise_rows.append({
                    "Subtype A": cell.get("subtype_a", "Unknown"),
                    "Subtype B": cell.get("subtype_b", "Unknown"),
                    "Test": cell.get("test", "n/a"),
                    "Effect": cell.get("effect"),
                    "p_value": cell.get("p_value"),
                    "q_value": cell.get("q_value"),
                    "n_a": cell.get("n_a"),
                    "n_b": cell.get("n_b"),
                })
            else:
                pairwise_rows.append({
                    "Subtype": cell.get("subtype", "Unknown"),
                    "Level A": cell.get("level_a", "Unknown"),
                    "Level B": cell.get("level_b", "Unknown"),
                    "Odds Ratio": cell.get("odds_ratio"),
                    "p_value": cell.get("p_value"),
                    "q_value": cell.get("q_value"),
                    "a_subtype": cell.get("a_subtype"),
                    "b_subtype": cell.get("b_subtype"),
                })

        if pairwise_rows:
            pd.DataFrame(pairwise_rows).to_csv(
                os.path.join(clinical_dir, f"{slug}_pairwise.csv"),
                index=False,
            )

        if analysis_kind == "continuous":
            if stats.get("median_records"):
                pd.DataFrame(stats["median_records"]).to_csv(
                    os.path.join(clinical_dir, f"{slug}_subtype_summary.csv"),
                    index=False,
                )
            if stats.get("normality_records"):
                pd.DataFrame(stats["normality_records"]).to_csv(
                    os.path.join(clinical_dir, f"{slug}_shapiro.csv"),
                    index=False,
                )
        else:
            if stats.get("significant_cells"):
                pd.DataFrame(stats["significant_cells"]).to_csv(
                    os.path.join(clinical_dir, f"{slug}_associated_cells.csv"),
                    index=False,
                )

        entry.pop("static_image_300dpi", None)
        entry.pop("static_image_source", None)

        try:
            data_static_path = save_static_clinical_plot(entry, clinical_img_dir)
            if data_static_path:
                entry["data_static_image"] = os.path.join("img", os.path.basename(data_static_path))
        except Exception:
            pass

    with open(os.path.join(clinical_dir, "clinical_association_summary.json"), "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=lambda o: o if isinstance(o, (str, int, float, bool)) or o is None else str(o))
    pd.DataFrame(summary_rows).to_csv(os.path.join(clinical_dir, "clinical_association_summary.csv"), index=False)

    if analysis_config is not None:
        with open(os.path.join(clinical_dir, "clinical_association_metadata.json"), "w") as f:
            json.dump(
                analysis_config,
                f,
                indent=2,
                ensure_ascii=False,
                default=lambda o: o if isinstance(o, (str, int, float, bool)) or o is None else str(o),
            )

    html_report = build_clinical_association_report_html(output_dir, summary, study_name=study_name)
    with open(os.path.join(output_dir, "clinical_association_report.html"), "w", encoding="utf-8") as f:
        f.write(html_report)
    return clinical_dir


def build_clinical_association_report_html(output_dir, summary, study_name=None):
    import html as html_lib_local

    metadata = _load_clinical_association_metadata(output_dir)
    agreement_threshold = metadata.get("agreement_threshold_pct")
    use_all_samples = bool(metadata.get("use_all_samples"))
    selected_variables = metadata.get("clinical_vars", [])

    title = "Clinical Association Report"
    body_parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        f"<title>{title}</title>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<style>",
        "body{font-family:Arial,sans-serif;background:#f8fafc;color:#0f172a;margin:0;padding:24px;}",
        ".shell{max-width:1200px;margin:0 auto;}",
        ".hero,.card{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:20px;margin-bottom:18px;}",
        ".grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;}",
        ".summary-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin-bottom:18px;}",
        ".summary-box{border:1px solid #e2e8f0;border-radius:12px;padding:14px 16px;background:#ffffff;}",
        ".summary-box .label{color:#64748b;font-size:12px;}",
        ".summary-box .value{font-weight:700;color:#0f172a;margin-top:4px;}",
        ".meta{color:#64748b;font-size:13px;}",
        ".table{width:100%;border-collapse:collapse;overflow:hidden;}",
        ".table th,.table td{border-bottom:1px solid #e2e8f0;padding:8px 10px;font-size:13px;text-align:left;vertical-align:top;}",
        ".table th{background:#ecfeff;}",
        ".section-title{margin:0 0 10px 0;font-size:18px;}",
        ".muted{color:#64748b;font-size:12px;}",
        "</style></head><body><div class='shell'>",
        f"<div class='hero'><h1>{title}</h1><div class='meta'>Project: {html_lib_local.escape(study_name or os.path.basename(output_dir))}</div></div>",
    ]

    summary_boxes = [
        ("Agreement filter", "Use all samples" if use_all_samples else f"{agreement_threshold}% agreement threshold" if agreement_threshold is not None else "n/a"),
        ("Selected variables", ", ".join(map(str, selected_variables)) if selected_variables else "n/a"),
        ("Clinical file", "annotation.csv"),
    ]
    body_parts.append(
        "<div class='card'>"
        "<h2 class='section-title'>Analysis summary</h2>"
        "<div class='summary-grid'>"
        + "".join(
            f"<div class='summary-box'><div class='label'>{html_lib_local.escape(label)}</div><div class='value'>{html_lib_local.escape(value)}</div></div>"
            for label, value in summary_boxes
        )
        + "</div></div>"
    )

    stat_rows = []
    for item in summary:
        summary_stats = item.get("variable_summary", {}) or {}
        stat_rows.append(
            {
                "Clinical variable": item.get("clinical_var", "Unknown"),
                "Analysis kind": item.get("analysis_kind", "n/a"),
                "N": summary_stats.get("n", item.get("total_samples", "n/a")),
                "Mean": summary_stats.get("mean", "n/a"),
                "Median": summary_stats.get("median", "n/a"),
                "Std": summary_stats.get("std", "n/a"),
            }
        )

    if stat_rows:
        stat_table = pd.DataFrame(stat_rows)
        body_parts.append(
            "<div class='card'>"
            "<h2 class='section-title'>Clinical variable statistics</h2>"
            f"{stat_table.to_html(index=False, classes='table', border=0, justify='left', float_format=lambda x: f'{x:.3f}' if isinstance(x, (int, float)) else x)}"
            "</div>"
        )

    for item in summary:
        clinical_var = html_lib_local.escape(str(item.get("clinical_var", "Unknown")))
        method = html_lib_local.escape(str(item.get("method", "n/a")))
        p_value = item.get("p_value")
        try:
            p_value = f"{float(p_value):.4g}"
        except Exception:
            p_value = "n/a"
        fig_json = item.get("figure_json", {})
        try:
            fig = go.Figure(fig_json)
            fig_html = fig.to_html(full_html=False, include_plotlyjs="cdn", config={"displaylogo": False})
        except Exception:
            fig_html = "<div class='muted'>Figure could not be rendered.</div>"

        body_parts.append(
            "<div class='card'>"
            f"<h2 style='margin-top:0'>{clinical_var}</h2>"
            f"<div class='meta'>Method: {method} | p-value: {p_value} | Samples: {item.get('total_samples', 'n/a')}</div>"
            f"<div class='grid'><div>{fig_html}</div><div>{_summary_stats_html(item)}</div></div>"
            "</div>"
        )

    body_parts.append("</div></body></html>")
    return "".join(body_parts)


def _summary_stats_html(item):
    import html as html_lib_local

    rows = [
        ("Analysis kind", item.get("analysis_kind", "n/a")),
        ("Top subtype", item.get("top_enriched_subtype", "n/a")),
        ("Test", item.get("method", "n/a")),
        ("Statistic", f"{item.get('statistic_label', 'Statistic')}: {item.get('statistic_value', 'n/a')}"),
        ("P-value", item.get("p_value", "n/a")),
    ]
    html_rows = "".join(
        f"<tr><th>{html_lib_local.escape(str(k))}</th><td>{html_lib_local.escape(str(v))}</td></tr>"
        for k, v in rows
    )
    return f"<table class='table'><tbody>{html_rows}</tbody></table>"


def build_clinical_association_figures(output_dir, clinical_vars, agreement_threshold=0.7, use_all_samples=False, orientation="subtype_x"):
    merged, _, _ = load_study_frames(output_dir)
    if merged is None:
        raise ValueError("Required clinical association files are missing.")
    study_subtype_color_map = _build_study_subtype_color_map(merged)
    filtered = filter_by_agreement(merged, use_all_samples=use_all_samples, agreement_threshold=agreement_threshold)
    if filtered.empty:
        raise ValueError(
            "No samples passed the selected agreement threshold. "
            "Try lowering the threshold or enable 'Use all samples'."
        )

    figures = []
    for clinical_var in clinical_vars:
        if clinical_var not in filtered.columns:
            continue
        numeric_values = pd.to_numeric(filtered[clinical_var], errors="coerce").dropna()
        variable_summary = {
            "n": int(numeric_values.shape[0]) if not numeric_values.empty else 0,
            "mean": float(numeric_values.mean()) if not numeric_values.empty else None,
            "median": float(numeric_values.median()) if not numeric_values.empty else None,
            "std": float(numeric_values.std(ddof=1)) if numeric_values.shape[0] > 1 else None,
        }
        if _is_continuous_variable(filtered[clinical_var]):
            fig = build_continuous_figure(filtered, clinical_var, orientation=orientation, subtype_color_map=study_subtype_color_map)
            try:
                stats = _compute_continuous_statistics(filtered, clinical_var)
            except Exception as exc:
                stats = {"analysis_kind": "continuous", "error": str(exc)}
            if "error" not in stats:
                subtype_order = stats.get("subtype_order") or _ordered_categories(filtered["primary_subtype"].tolist())
                plot_traces = []
                for idx, subtype in enumerate(subtype_order):
                    values = filtered.loc[filtered["primary_subtype"] == subtype, clinical_var].astype(float).tolist()
                    if not values:
                        continue
                    subtype_color = study_subtype_color_map.get(subtype, SUBTYPE_PALETTE[idx % len(SUBTYPE_PALETTE)])
                    if (orientation or "subtype_x") == "clinical_x":
                        plot_traces.append({"name": subtype, "x": values, "orientation": "h", "marker": {"color": subtype_color}})
                    else:
                        plot_traces.append({"name": subtype, "y": values, "orientation": "v", "marker": {"color": subtype_color}})
                stats["plot_traces"] = plot_traces
        else:
            fig = build_categorical_figure(filtered, clinical_var, orientation=orientation, subtype_color_map=study_subtype_color_map)
            try:
                stats = _compute_categorical_statistics(filtered, clinical_var)
            except Exception as exc:
                stats = {"analysis_kind": "categorical", "error": str(exc)}
            if "error" not in stats:
                contingency = stats.get("contingency")
                plot_traces = []
                if isinstance(contingency, pd.DataFrame) and not contingency.empty:
                    if (orientation or "subtype_x") == "clinical_x":
                        clinical_levels = stats.get("clinical_levels") or list(contingency.index)
                        subtype_levels = stats.get("subtype_levels") or list(contingency.columns)
                        for idx, subtype in enumerate(subtype_levels):
                            y_vals = [int(contingency.loc[level, subtype]) for level in clinical_levels]
                            subtype_color = study_subtype_color_map.get(subtype, SUBTYPE_PALETTE[idx % len(SUBTYPE_PALETTE)])
                            plot_traces.append({"name": subtype, "x": clinical_levels, "y": y_vals, "marker": {"color": subtype_color}})
                    else:
                        clinical_levels = stats.get("clinical_levels") or list(contingency.index)
                        subtype_levels = stats.get("subtype_levels") or list(contingency.columns)
                        for idx, level in enumerate(clinical_levels):
                            y_vals = [int(contingency.loc[level, subtype]) for subtype in subtype_levels]
                            plot_traces.append({"name": level, "x": subtype_levels, "y": y_vals, "marker": {"color": DEFAULT_COLORS[idx % len(DEFAULT_COLORS)]}})
                stats["plot_traces"] = plot_traces
        stats["orientation"] = orientation or "subtype_x"
        stats["variable_summary"] = variable_summary
        try:
            fig.update_layout(meta={"subtype_color_map": study_subtype_color_map})
        except Exception:
            pass
        figures.append((clinical_var, fig, stats))
    return figures
