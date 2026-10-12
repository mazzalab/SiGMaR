import html as html_lib
import base64
import json
import os
import re
from collections import Counter
from io import BytesIO

from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from PIL import Image, ImageDraw, ImageFont
from config import PROJECT_ROOT, format_tumor_type, get_tumor_type_pill_style, style_dict_to_css, get_button_style


def _get_value(entry, key, default="-"):
    value = entry.get(key, default)
    if isinstance(value, list) and value:
        return value[0]
    return value if value not in (None, "") else default


def _render_table_cell(value):
    return html.Small(str(value), className="text-muted")


def _available_result_method_groups(data):
    if not data:
        return []
    return [
        group for group in RESULT_METHOD_GROUPS
        if any(any(key in entry for key in group["keys"]) for entry in data)
    ]


def _method_group_text(entry, group_id):
    if group_id == "ntp":
        return str(_get_value(entry, "ntp_pred"))
    if group_id == "ssgsea":
        return str(_get_value(entry, "ss_gsea_pred"))
    if group_id == "pce":
        return "\n".join([
            f"P: {_get_value(entry, 'pce_pearson')}",
            f"C: {_get_value(entry, 'pce_cosine')}",
            f"E: {_get_value(entry, 'pce_euclidean')}",
        ])
    if group_id == "tmp":
        return "\n".join([
            f"AKL: {_get_value(entry, 'result_aklimate')}",
            f"JAD: {_get_value(entry, 'result_jadbio')}",
            f"SKG: {_get_value(entry, 'result_skgrid')}",
            f"SUB: {_get_value(entry, 'result_subscope')}",
            f"CF: {_get_value(entry, 'result_cloudforest')}",
        ])
    if group_id == "cms":
        return "\n".join([
            f"RF: {_get_value(entry, 'cms_rf_pred')}",
            f"SSP: {_get_value(entry, 'cms_ssp_pred')}",
            f"Caller: {_get_value(entry, 'cms_caller_pred')}",
        ])
    if group_id == "consensus_ov":
        return str(_get_value(entry, "consensus_ov_pred"))
    if group_id == "breast":
        return "\n".join([
            f"AIMS: {_get_value(entry, 'breast_aims_pred')}",
            f"sspbc: {_get_value(entry, 'breast_sspbc_pred')}",
        ])
    return "-"


def _method_group_cell(entry, group_id):
    text = _method_group_text(entry, group_id)
    if "\n" not in text:
        return _render_table_cell(text)
    return html.Div(
        [html.Small(line, className="d-block text-muted") for line in text.splitlines()],
        style={"fontSize": "0.75rem"},
    )


def _info_label(label, icon_id):
    return html.Span(
        [
            html.Span(label),
            html.Sup(
                html.Span(
                    "i",
                    id=icon_id,
                    className="ms-1",
                    style={
                        "display": "inline-flex",
                        "alignItems": "center",
                        "justifyContent": "center",
                        "width": "14px",
                        "height": "14px",
                        "borderRadius": "50%",
                        "border": "1px solid #94a3b8",
                        "color": "#64748b",
                        "fontSize": "10px",
                        "fontWeight": "700",
                        "lineHeight": "1",
                        "verticalAlign": "super",
                    },
                )
            ),
        ]
    )


def _sort_button_symbol(field, active_field, sort_order):
    if field != active_field:
        return "▲▼"
    return "▲" if str(sort_order).lower() == "asc" else "▼"


def _sortable_header(label, field, active_field, sort_order, icon_id):
    return html.Span(
        [
            html.Span(label, className="text-primary"),
            dbc.Button(
                _sort_button_symbol(field, active_field, sort_order),
                id={"type": "sort_btn", "field": field},
                size="sm",
                color="link",
                className="p-0 ms-1 align-baseline text-decoration-none",
                style={
                    "fontSize": "10px",
                    "lineHeight": "1",
                    "color": "#64748b",
                    "border": "none",
                    "boxShadow": "none",
                },
            ),
            html.Sup(
                html.Span(
                    "i",
                    id=icon_id,
                    className="ms-1",
                    style={
                        "display": "inline-flex",
                        "alignItems": "center",
                        "justifyContent": "center",
                        "width": "14px",
                        "height": "14px",
                        "borderRadius": "50%",
                        "border": "1px solid #94a3b8",
                        "color": "#64748b",
                        "fontSize": "10px",
                        "fontWeight": "700",
                        "lineHeight": "1",
                        "verticalAlign": "super",
                    },
                )
            ),
        ],
        className="d-inline-flex align-items-center",
    )


def _build_weighting_card(consensus_mode, tumor_type):
    """Collapsed "Consensus Evaluation" card shown on every Results page: how the Final
    Consensus and the Agreement Score were obtained, in words. Two cases, the validated
    Dawid-Skene weighting (externally validated tumors run with weighting on) and the
    plain equal vote merge.R falls back to everywhere else.

    The per-method, per-subtype reliability table that used to sit in this card was
    removed on request (2026-09-25): the numbers are the diagonal of each method's
    fitted confusion matrix, they are only part of what the weighting applies (the
    off-diagonal entries matter as much), and they read as noise to someone checking a
    sample's call. They remain available in utilities/method_confusion.tsv and in
    Additional file 1 of the paper."""
    title = "Consensus Evaluation"
    if consensus_mode != "ds":
        explain = ("Each method that returns a call contributes one equal vote. The subtype receiving the most votes is selected as the Final Consensus, "
                   "while the Agreement Score represents the proportion of votes supporting that consensus. If two or more subtypes are tied, or no clear "
                   "consensus is reached, the sample is marked as Uncertain.")
        strategy = "Equal-vote consensus"
    else:
        explain = ("Each method is weighted according to how reliably it identifies each subtype in the validation cohort for this tumor type. Methods "
                   "contribute more when their accuracy is well established and less when it is uncertain. The Final Consensus is the subtype that best "
                   "fits the overall pattern of calls, while the Agreement Score indicates how strongly the available evidence supports that consensus.")
        strategy = "Weighted consensus (validated per-subtype weighting)"
    return html.Details(
        [
            html.Summary(title, className="fw-semibold", style={"cursor": "pointer"}),
            html.P([html.Strong("Strategy: "), strategy], className="small mb-1 mt-2"),
            html.P(explain, className="text-muted small mb-0"),
        ],
        className="shadow-sm border-0 mb-3 p-3 bg-white rounded",
    )


SAMPLE_VIEW_METHOD_COLUMNS = [
    "result_aklimate",
    "result_cloudforest",
    "result_jadbio",
    "result_skgrid",
    "result_subscope",
    "cms_rf_pred",
    "cms_ssp_pred",
    "cms_caller_pred",
    "pce_pearson",
    "pce_cosine",
    "pce_euclidean",
    "ss_gsea_pred",
    "ntp_pred",
    "consensus_ov_pred",
    "breast_aims_pred",
    "breast_sspbc_pred",
]


RESULT_METHOD_GROUPS = [
    {"id": "ntp", "label": "NTP", "keys": ["ntp_pred"]},
    {"id": "ssgsea", "label": "ssGSEA", "keys": ["ss_gsea_pred"]},
    {"id": "pce", "label": "PCE (Pear/Cos/Euc)", "keys": ["pce_pearson", "pce_cosine", "pce_euclidean"]},
    {"id": "tmp", "label": "TMP Predictors", "keys": ["result_aklimate", "result_jadbio", "result_skgrid", "result_subscope", "result_cloudforest"]},
    {"id": "cms", "label": "CMS Predictors", "keys": ["cms_rf_pred", "cms_ssp_pred", "cms_caller_pred"]},
    {"id": "consensus_ov", "label": "Consensus OV", "keys": ["consensus_ov_pred"]},
    {"id": "breast", "label": "BreastSubtypeR", "keys": ["breast_aims_pred", "breast_sspbc_pred"]},
]


SUBTYPE_PALETTE = [
    "#0F766E",
    "#F59E0B",
    "#1D4ED8",
    "#F97316",
    "#14B8A6",
    "#EA580C",
    "#2DD4BF",
    "#FB923C",
    "#84CC16",
    "#5EEAD4",
    "#FDBA74",
    "#06B6D4",
    "#A7F3D0",
    "#8B5CF6",
]


def _clean_label(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    label = str(value).strip()
    if not label or label.upper() == "N/A":
        return None
    return label


def _label_sort_key(label):
    if label is None:
        return (2, "")
    text = str(label).strip()
    if text.isdigit():
        return (0, int(text))
    try:
        return (0, float(text))
    except Exception:
        return (1, text.lower())


def _build_subtype_color_map(labels):
    unique_labels = []
    for label in labels:
        cleaned = _clean_label(label)
        if cleaned and cleaned not in unique_labels:
            unique_labels.append(cleaned)
    ordered_labels = sorted(unique_labels, key=_label_sort_key)
    return {label: SUBTYPE_PALETTE[i % len(SUBTYPE_PALETTE)] for i, label in enumerate(ordered_labels)}


def _hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def _text_color_for_fill(hex_color):
    r, g, b = _hex_to_rgb(hex_color)
    luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
    return "#ffffff" if luminance < 0.56 else "#0f172a"


def _build_discrete_colorscale(colors):
    if not colors:
        return [[0, "#cbd5e1"], [1, "#cbd5e1"]]
    if len(colors) == 1:
        return [[0, colors[0]], [1, colors[0]]]

    n = len(colors) - 1
    scale = []
    for idx, color in enumerate(colors):
        pos = idx / n
        scale.append([pos, color])
        scale.append([pos, color])
    return scale


def _method_display_name(column_name):
    return (
        column_name.replace("result_", "")
        .replace("_pred", "")
        .replace("_", " ")
        .lower()
    )


def _logo_path(filename):
    return os.path.join(PROJECT_ROOT, "logo", filename)


def _logo_data_uri(filename):
    path = _logo_path(filename)
    if not os.path.exists(path):
        return ""
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    ext = os.path.splitext(filename)[1].lstrip(".").lower() or "png"
    return f"data:image/{ext};base64,{encoded}"


def _load_report_dataframe(data):
    df = pd.json_normalize(data)
    for col in df.columns:
        if df[col].apply(lambda value: isinstance(value, list)).any():
            df[col] = df[col].apply(
                lambda value: ", ".join(map(str, value)) if isinstance(value, list) and value else value
            )
    return df


def _build_subtype_view_figure(data, subtype_color_map=None):
    df = _load_report_dataframe(data)
    if "primary_subtype" not in df.columns or df.empty:
        return go.Figure()

    pie_data = (
        df.groupby("primary_subtype")
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )
    color_map = subtype_color_map or _build_subtype_color_map(
        list(df["primary_subtype"].tolist()) +
        [value for col in SAMPLE_VIEW_METHOD_COLUMNS if col in df.columns for value in df[col].tolist()]
    )
    marker_colors = [color_map.get(str(label), SUBTYPE_PALETTE[0]) for label in pie_data["primary_subtype"]]
    pull_vec = [0.16 if i == 0 else 0 for i in range(len(pie_data))]

    fig = go.Figure(
        data=[
            go.Pie(
                labels=pie_data["primary_subtype"],
                values=pie_data["count"],
                textinfo="percent+label",
                textposition="outside",
                pull=pull_vec,
                marker=dict(
                    colors=marker_colors,
                    line=dict(color="#ffffff", width=2),
                ),
                sort=False,
            )
        ]
    )
    fig.update_layout(
        title=dict(
            text="<b>Pie Chart</b>",
            #font=dict(size=22, color="#004D40"),
            x=0.1,
        ),
        showlegend=True,
        margin=dict(t=90, b=40, l=40, r=40),
        paper_bgcolor="white",
        plot_bgcolor="white",
    )
    return fig


def _build_sample_view_figure(data, subtype_color_map=None):
    df = _load_report_dataframe(data)
    if df.empty or "Samples" not in df.columns:
        return go.Figure()

    if "confidence" in df.columns:
        # Ties on confidence are common in small cohorts; sort_values' default "quicksort"
        # isn't stable, so two samples sharing a score could land in a different relative
        # order between calls - breaking ties on Samples keeps this and the matching sort
        # in the other Sample View renderer reproducible and consistent with each other.
        sort_cols = ["confidence", "Samples"] if "Samples" in df.columns else ["confidence"]
        df = df.sort_values(sort_cols, ascending=True, kind="stable")

    available_cols = [col for col in SAMPLE_VIEW_METHOD_COLUMNS if col in df.columns]
    if not available_cols:
        return go.Figure()

    color_labels = []
    if "primary_subtype" in df.columns:
        color_labels.extend(df["primary_subtype"].tolist())
    color_labels.extend([value for col in available_cols for value in df[col].tolist()])
    full_color_map = _build_subtype_color_map(color_labels)
    # subtype_color_map (when passed in) only ever covers primary_subtype values, to stay
    # consistent with the rest of the report - here it was used as a wholesale replacement,
    # so any individual-method prediction it didn't cover (e.g. every non-consensus subtype
    # in a cohort where every sample's final call happens to be the same) fell through to the
    # one shared SUBTYPE_PALETTE[0] fallback below and collided with whichever label legitimately
    # owned that color, making genuinely different predictions render identically. Overlaying it
    # on the full map keeps those shared colors while still giving every other label its own.
    color_map = {**full_color_map, **(subtype_color_map or {})}

    long_rows = []
    for _, row in df.iterrows():
        sample = row.get("Samples", "N/A")
        confidence = row.get("confidence", 0)
        for col in available_cols:
            value = row.get(col)
            if value is None or value == "" or value == "N/A" or (isinstance(value, float) and pd.isna(value)):
                continue
            method = (
                col.replace("details.", "")
                .replace("result_", "")
                .replace("_pred", "")
                .replace("_", " ")
                .upper()
            )
            long_rows.append({
                "Samples": sample,
                "Prediction": str(value),
                "Method": method,
                "confidence": confidence,
            })

    if not long_rows:
        return go.Figure()

    long_df = pd.DataFrame(long_rows)
    sample_order = list(dict.fromkeys(df["Samples"].tolist()))
    long_df["Samples"] = pd.Categorical(long_df["Samples"], categories=sample_order, ordered=True)

    agg = long_df.groupby(["Samples", "Prediction"], observed=False).size().reset_index(name="count")
    unique_predictions = list(dict.fromkeys(agg["Prediction"].tolist()))
    dynamic_height = max(780, (len(sample_order) * 28) + 220)
    fig = go.Figure()
    for pred in unique_predictions:
        pred_df = agg[agg["Prediction"] == pred]
        fig.add_trace(
            go.Bar(
                y=pred_df["Samples"].astype(str),
                x=pred_df["count"],
                name=pred,
                orientation="h",
                marker=dict(color=color_map.get(pred, SUBTYPE_PALETTE[0])),
                hovertemplate="Sample=%{y}<br>Prediction=" + pred + "<br>Count=%{x}<extra></extra>",
            )
        )

    fig.update_layout(
        title=dict(
            text="<b>Barplot</b>",
            x=0.1,
        ),
        barmode="stack",
        bargap=0.3,
        legend=dict(title=dict(text="Tumor Subtype")),
        margin=dict(l=150, r=50, b=20, t=90),
        height=dynamic_height,
        dragmode=False,
        paper_bgcolor="white",
        plot_bgcolor="white",
    )
    fig.update_xaxes(showgrid=False, zeroline=False, showticklabels=False, fixedrange=True)
    fig.update_yaxes(title="", tickfont=dict(size=8), automargin=True, fixedrange=True)
    return fig


def _graphic_section(title, subtitle, figure, accent, dpi_id):
    return dbc.Card(
        dbc.CardBody([
            dbc.Row(
                [
                    dbc.Col(html.H3(title, className="fw-bold mb-1", style={"color": accent}), width="auto"),
                ],
                className="align-items-start mb-2",
            ),

            dbc.Row(
                [
                    dbc.Col(
                        html.Div(
                            [
                                dbc.RadioItems(
                                    id=dpi_id,
                                    options=[
                                        {"label": "150 dpi", "value": 150},
                                        {"label": "300 dpi", "value": 300},
                                    ],
                                    value=150,
                                    inline=True,
                                    className="mb-2",
                                ),
                                dbc.ButtonGroup(
                                    [
                                        dbc.Button("PNG", id=f"download_{title.lower().replace(' ', '_')}_png_btn", size="md", outline=True, color="secondary"),
                                        dbc.Button("TIFF", id=f"download_{title.lower().replace(' ', '_')}_tiff_btn", size="md", outline=True, color="secondary"),
                                        dbc.Button("PDF", id=f"download_{title.lower().replace(' ', '_')}_pdf_btn", size="md", outline=True, color="secondary"),
                                    ]
                                ),
                            ],
                            className="ms-auto d-flex flex-column align-items-start me-2",
                        ),
                        width="auto",
                        className="ms-auto align-self-start",
                    ),
                ],
                className="align-items-start mb-2",
            ),
            
            html.P(subtitle, className="text-muted mb-3"),
            dcc.Graph(figure=figure, config={"displayModeBar": False}, className="w-100"),
        ]),
        className="shadow-sm border-0 mb-4",
        style={
            "borderRadius": "1.25rem",
            "background": "linear-gradient(135deg, #ffffff 0%, #f8fafc 100%)",
        },
    )


def _load_clinical_association_summary(output_dir):
    summary_path = os.path.join(output_dir, "clinical_association", "clinical_association_summary.json")
    if not os.path.exists(summary_path):
        return []
    try:
        with open(summary_path, "r") as f:
            summary = json.load(f)
        return summary if isinstance(summary, list) else []
    except Exception:
        return []


def _clinical_association_static_image_path(output_dir, clinical_var, dpi=150):
    slug = re.sub(r"[^a-z0-9]+", "_", str(clinical_var).lower()).strip("_") or "clinical_association"
    return os.path.join(output_dir, "clinical_association", f"{slug}_static_{int(dpi)}dpi.png")


def _load_clinical_association_color_map(output_dir):
    summary = _load_clinical_association_summary(output_dir)
    if not summary:
        return None
    for item in summary:
        figure_json = item.get("figure_json", {}) or {}
        layout = figure_json.get("layout", {}) if isinstance(figure_json, dict) else {}
        meta = layout.get("meta", {}) if isinstance(layout, dict) else {}
        color_map = meta.get("subtype_color_map") if isinstance(meta, dict) else None
        if isinstance(color_map, dict) and color_map:
            return color_map
    return None


def _load_clinical_association_metadata(output_dir):
    metadata_path = os.path.join(output_dir, "clinical_association", "clinical_association_metadata.json")
    if not os.path.exists(metadata_path):
        return {}
    try:
        with open(metadata_path, "r") as f:
            metadata = json.load(f)
        return metadata if isinstance(metadata, dict) else {}
    except Exception:
        return {}


def _format_clinical_association_p_value(value):
    try:
        value = float(value)
    except Exception:
        return "n/a"
    if value < 0.001:
        return "< 0.001"
    return f"{value:.4f}"


def _format_clinical_association_numeric(value):
    try:
        value = float(value)
    except Exception:
        return "n/a"
    if pd.isna(value):
        return "n/a"
    return f"{value:.3f}"


def _continuous_stat_summary_rows(item):
    rows = []
    for cell in item.get("median_records", []) or []:
        rows.append(
            {
                "Subtype": cell.get("subtype", "Unknown"),
                "Mean": _format_clinical_association_numeric(cell.get("mean")),
                "Median": _format_clinical_association_numeric(cell.get("median")),
                "Std dev": _format_clinical_association_numeric(cell.get("std")),
                "N": cell.get("n", "n/a"),
            }
        )
    return rows


def _clinical_association_table_card(title, rows, columns, empty_message=None, header_color="#ecfdf5", border_color="#d1fae5", highlight_significant=False):
    if not rows:
        if not empty_message:
            return None
        return dbc.Card(
            dbc.CardBody([
                html.Div(title, className="fw-semibold mb-2"),
                html.Div(empty_message, className="small text-muted"),
            ]),
            className="border-0 shadow-sm bg-white mb-3",
        )

    return dbc.Card(
        dbc.CardBody([
            html.Div(title, className="fw-semibold mb-2"),
            dash_table.DataTable(
                data=rows,
                columns=columns,
                hidden_columns=["__significant"] if highlight_significant else [],
                page_action="none",
                style_table={"overflowX": "auto"},
                style_cell={
                    "textAlign": "left",
                    "padding": "6px",
                    "fontSize": "12px",
                    "whiteSpace": "normal",
                    "height": "auto",
                },
                style_header={
                    "backgroundColor": header_color,
                    "fontWeight": "700",
                    "border": f"1px solid {border_color}",
                },
                style_data={"border": "1px solid #e5e7eb"},
                style_data_conditional=[
                    {
                        "if": {"filter_query": "{__significant} = 'yes'"},
                        "fontWeight": "700",
                        "backgroundColor": "#f0fdf4",
                    }
                ] if highlight_significant else [],
            ),
        ]),
        className="border-0 shadow-sm bg-white mb-3",
    )


def _continuous_stat_summary_table(item):
    rows = _continuous_stat_summary_rows(item)
    if not rows:
        return None
    columns = [
        {"name": "Subtype", "id": "Subtype"},
        {"name": "Mean", "id": "Mean"},
        {"name": "Median", "id": "Median"},
        {"name": "Std dev", "id": "Std dev"},
        {"name": "N", "id": "N"},
    ]
    return _clinical_association_table_card("Statistic summaries", rows, columns)


def _recolor_clinical_association_figure(figure, analysis_kind):
    if analysis_kind != "continuous":
        return figure

    trace_names = []
    for trace in getattr(figure, "data", []) or []:
        name = _clean_label(getattr(trace, "name", None))
        if name and name not in trace_names:
            trace_names.append(name)

    meta_color_map = None
    try:
        meta_color_map = getattr(getattr(figure, "layout", None), "meta", None)
        if isinstance(meta_color_map, dict):
            meta_color_map = meta_color_map.get("subtype_color_map")
    except Exception:
        meta_color_map = None

    color_map = meta_color_map if isinstance(meta_color_map, dict) and meta_color_map else _build_subtype_color_map(trace_names)
    for idx, trace in enumerate(getattr(figure, "data", []) or []):
        name = _clean_label(getattr(trace, "name", None))
        color = color_map.get(name, SUBTYPE_PALETTE[idx % len(SUBTYPE_PALETTE)])
        try:
            if getattr(trace, "marker", None) is not None:
                trace.marker.color = color
        except Exception:
            pass
        try:
            if getattr(trace, "line", None) is not None:
                trace.line.color = color
        except Exception:
            pass
        try:
            trace.fillcolor = color
        except Exception:
            pass

    return figure


def _continuous_stat_summary_html(item):
    rows = _continuous_stat_summary_rows(item)
    if not rows:
        return ""
    html_rows = "".join(
        "<tr>"
        f"<td>{html_lib.escape(str(row['Subtype']))}</td>"
        f"<td>{html_lib.escape(str(row['Mean']))}</td>"
        f"<td>{html_lib.escape(str(row['Median']))}</td>"
        f"<td>{html_lib.escape(str(row['Std dev']))}</td>"
        f"<td>{html_lib.escape(str(row['N']))}</td>"
        "</tr>"
        for row in rows
    )
    return (
        "<div class='clinical-card'>"
        "<h3 style='margin-top:0'>Statistic summaries</h3>"
        "<table class='clinical-table'>"
        "<thead><tr><th>Subtype</th><th>Mean</th><th>Median</th><th>Std dev</th><th>N</th></tr></thead>"
        f"<tbody>{html_rows}</tbody>"
        "</table>"
        "</div>"
    )


def _clinical_association_posthoc_rows(item):
    analysis_kind = item.get("analysis_kind", "categorical")
    p_value = item.get("p_value")
    try:
        p_value = float(p_value)
    except Exception:
        p_value = None

    if p_value is None or p_value >= 0.05:
        return [], []

    def pvalue_sort_key(record):
        try:
            return (0, float(record.get("p_value")))
        except Exception:
            return (1, float("inf"))

    records = sorted(item.get("pairwise_cells", []) or [], key=pvalue_sort_key)
    if analysis_kind == "categorical":
        rows = []
        for cell in records:
            is_significant = float(cell.get("q_value", 1.0)) < 0.05
            rows.append(
                {
                    "Subtype": cell.get("subtype", "Unknown"),
                    "Comparison": f"{cell.get('level_a', 'Unknown')} vs {cell.get('level_b', 'Unknown')}",
                    "OR": f"{float(cell.get('odds_ratio', 0.0)):.3f}",
                    "p-value": f"{float(cell.get('p_value', 1.0)):.4g}",
                    "q-value (padj)": f"{float(cell.get('q_value', 1.0)):.4g}",
                    "__significant": "yes" if is_significant else "no",
                }
            )
        columns = [
            {"name": "Subtype", "id": "Subtype"},
            {"name": "Comparison", "id": "Comparison"},
            {"name": "OR", "id": "OR"},
            {"name": "p-value", "id": "p-value"},
            {"name": "q-value (padj)", "id": "q-value (padj)"},
        ]
        return rows, columns

    rows = []
    for cell in records:
        is_significant = float(cell.get("q_value", 1.0)) < 0.05
        rows.append(
            {
                "Subtype A": cell.get("subtype_a", "Unknown"),
                "Subtype B": cell.get("subtype_b", "Unknown"),
                "Test": cell.get("test", "Mann-Whitney U"),
                "Effect": f"{float(cell.get('effect', 0.0)):.3f}",
                "p-value": f"{float(cell.get('p_value', 1.0)):.4g}",
                "q-value (padj)": f"{float(cell.get('q_value', 1.0)):.4g}",
                "__significant": "yes" if is_significant else "no",
            }
        )
    columns = [
        {"name": "Subtype A", "id": "Subtype A"},
        {"name": "Subtype B", "id": "Subtype B"},
        {"name": "Test", "id": "Test"},
        {"name": "Effect", "id": "Effect"},
        {"name": "p-value", "id": "p-value"},
        {"name": "q-value (padj)", "id": "q-value (padj)"},
    ]
    return rows, columns


def _clinical_association_stats_card(item):
    analysis_kind = item.get("analysis_kind", "categorical")
    if item.get("error"):
        return dbc.Card(
            dbc.CardBody([
                html.H6("Statistics", className="mb-2"),
                html.Div("Statistics unavailable.", className="fw-semibold"),
                html.Div(str(item["error"]), className="small text-muted"),
            ]),
            className="h-100 border-0 shadow-sm bg-light",
        )

    p_value = _format_clinical_association_p_value(item.get("p_value"))
    method = item.get("method", "n/a")
    total_samples = item.get("total_samples", 0)
    top_subtype = item.get("top_enriched_subtype", "n/a")
    if analysis_kind == "categorical":
        middle_label = "Table"
        middle_value = f"{item.get('rows', 0)} x {item.get('cols', 0)}"
        bottom_note = "Fisher exact is used for 2x2 tables; otherwise chi-square is used."
        cells_title = "Associated cells"
    else:
        middle_label = "Subtype groups"
        middle_value = str(item.get("groups", 0))
        bottom_note = "Subtype medians and Shapiro tables are saved in the clinical_association folder inside the output."
        cells_title = "Subtype summaries"

    stats_rows = [
        ("Test", method),
        ("p-value", p_value),
        ("Samples", str(total_samples)),
        (middle_label, middle_value),
        ("Top subtype", top_subtype),
    ]
    stats_table = dash_table.DataTable(
        data=[{"Label": k, "Value": v} for k, v in stats_rows],
        columns=[{"name": "Label", "id": "Label"}, {"name": "Value", "id": "Value"}],
        page_action="none",
        style_table={"overflowX": "auto"},
        style_cell={"textAlign": "left", "padding": "6px", "fontSize": "12px", "whiteSpace": "normal", "height": "auto"},
        style_header={"backgroundColor": "#ecfeff", "fontWeight": "700", "border": "1px solid #d1fae5"},
        style_data={"border": "1px solid #e5e7eb"},
    )

    content = [
        html.H6("Statistics", className="mb-2"),
        stats_table,
        html.Div(bottom_note, className="small text-muted mt-2"),
        html.Hr(className="my-3"),
        html.Div(cells_title, className="fw-semibold mb-2"),
    ]

    if analysis_kind == "categorical":
        significant_cells = item.get("significant_cells", []) or []
        if significant_cells:
            content.append(
                html.Ul(
                    [
                        html.Li(
                            f"Clinical level {cell.get('clinical_level', 'Unknown')} enriched for subtype {cell.get('subtype', 'Unknown')} "
                            f"(resid {float(cell.get('residual', 0.0)):+.2f}, obs {int(cell.get('observed', 0))}, exp {float(cell.get('expected', 0.0)):.1f})",
                            className="small",
                        )
                        for cell in significant_cells[:5]
                    ],
                    className="mb-0 ps-3",
                )
            )
        else:
            content.append(html.Div("No enriched cells passed the significance threshold.", className="small text-muted"))

    return dbc.Card(
        dbc.CardBody(content),
        className="h-100 border-0 shadow-sm bg-light",
    )


def _clinical_association_card(item):
    figure_json = item.get("figure_json", {})
    try:
        figure = go.Figure(figure_json)
    except Exception:
        figure = go.Figure()
    figure = _recolor_clinical_association_figure(figure, item.get("analysis_kind", "categorical"))

    rows, columns = _clinical_association_posthoc_rows(item)
    analysis_kind = item.get("analysis_kind", "categorical")
    summary_table = _continuous_stat_summary_table(item) if analysis_kind == "continuous" else None
    posthoc_table = _clinical_association_table_card(
        "Post hoc table",
        rows,
        columns,
        empty_message="Post hoc table is available only when the global test is significant.",
        highlight_significant=True,
    )

    return dbc.Card(
        dbc.CardBody([
            dbc.Row(
                [
                    dbc.Col(html.H5(item.get("clinical_var", "Unknown"), className="mb-0"), width="auto"),
                    dbc.Col(
                        html.Div(
                            [
                                dbc.RadioItems(
                                    id={"type": "ca_report_dpi", "clinical_var": item.get("clinical_var", "Unknown")},
                                    options=[
                                        {"label": "150 dpi", "value": 150},
                                        {"label": "300 dpi", "value": 300},
                                    ],
                                    value=150,
                                    inline=True,
                                    className="mb-2",
                                ),
                                dbc.ButtonGroup(
                                    [
                                        dbc.Button("PNG", id={"type": "ca_report_download_btn", "clinical_var": item.get("clinical_var", "Unknown"), "format": "png"}, size="md", outline=True, color="secondary"),
                                        dbc.Button("TIFF", id={"type": "ca_report_download_btn", "clinical_var": item.get("clinical_var", "Unknown"), "format": "tiff"}, size="md", outline=True, color="secondary"),
                                        dbc.Button("PDF", id={"type": "ca_report_download_btn", "clinical_var": item.get("clinical_var", "Unknown"), "format": "pdf"}, size="md", outline=True, color="secondary"),
                                    ],
                                ),
                            ],
                            className="ms-auto d-flex flex-column align-items-start me-2",
                        ),
                        width="auto",
                        className="ms-auto",
                    ),
                ],
                className="align-items-center mb-3",
            ),
            dbc.Row([
                dbc.Col(
                    dcc.Graph(
                        id={"type": "ca_report_graph", "clinical_var": item.get("clinical_var", "Unknown")},
                        figure=figure,
                        config={
                            "displaylogo": False,
                            "responsive": True,
                            "scrollZoom": False,
                            "modeBarButtonsToRemove": [
                                "zoom2d",
                                "pan2d",
                                "select2d",
                                "lasso2d",
                                "autoScale2d",
                                "resetScale2d",
                            ],
                        },
                        style={"height": "100%"},
                    ),
                    md=9,
                    xs=12,
                ),
                dbc.Col(_clinical_association_stats_card(item), md=3, xs=12),
            ], className="g-3 align-items-stretch"),
            summary_table if summary_table is not None else html.Div(),
            html.Div(className="mt-3"),
            posthoc_table,
        ]),
        className="shadow-sm border-0 mb-4",
    )


def _clinical_association_html_section(output_dir, summary, metadata=None):
    if not summary:
        return ""

    parts = [
        "<div class='clinical-section'>",
        "<div class='clinical-card'><h2 style='margin-top:0'>Clinical Association</h2><div class='clinical-muted'>Saved clinical association output</div></div>",
    ]
    # plotly.js is loaded once via CDN in build_html_report's <head> (its
    # only caller), so every fig.to_html() here skips re-loading it.
    for item in summary:
        try:
            figure_json = item.get("figure_json", {})
            fig = go.Figure(figure_json)
            fig = _recolor_clinical_association_figure(fig, item.get("analysis_kind", "categorical"))
            fig_html = fig.to_html(full_html=False, include_plotlyjs=False, config={"displaylogo": False})
        except Exception:
            fig_html = "<div class='clinical-muted'>Figure could not be rendered.</div>"
        if item.get("error"):
            meta_html = f"<div class='clinical-meta'>Statistics unavailable: {html_lib.escape(str(item['error']))}</div>"
            body_html = f"<div class='clinical-grid'><div>{fig_html}</div></div>"
        else:
            method = html_lib.escape(str(item.get("method", "n/a")))
            p_value = _format_clinical_association_p_value(item.get("p_value"))
            summary_html = _continuous_stat_summary_html(item) if item.get("analysis_kind", "categorical") == "continuous" else ""
            meta_html = f"<div class='clinical-meta'>Method: {method} | p-value: {p_value} | Samples: {item.get('total_samples', 'n/a')}</div>{summary_html}"
            body_html = f"<div class='clinical-grid'><div>{fig_html}</div><div>{_summary_stats_html(item)}</div></div>"
        parts.append(
            "<div class='clinical-card'>"
            f"<h3 style='margin-top:0'>{html_lib.escape(str(item.get('clinical_var', 'Unknown')))}</h3>"
            f"{meta_html}"
            f"{body_html}"
            "</div>"
        )
    parts.append("</div>")
    return "".join(parts)


def _summary_stats_html(item):
    import html as html_lib_local

    rows = [
        ("Analysis kind", item.get("analysis_kind", "n/a")),
        ("Top subtype", item.get("top_enriched_subtype", "n/a")),
        ("Test", item.get("method", "n/a")),
        ("Statistic", f"{item.get('statistic_label', 'Statistic')}: {item.get('statistic_value', 'n/a')}"),
        ("P-value", _format_clinical_association_p_value(item.get("p_value"))),
    ]
    html_rows = "".join(
        f"<tr><th>{html_lib_local.escape(str(k))}</th><td>{html_lib_local.escape(str(v))}</td></tr>"
        for k, v in rows
    )
    return f"<table class='clinical-table'><tbody>{html_rows}</tbody></table>"


def _get_report_dataframe(data):
    df = pd.json_normalize(data)
    for col in df.columns:
        if df[col].apply(lambda value: isinstance(value, list)).any():
            df[col] = df[col].apply(
                lambda value: ", ".join(map(str, value)) if isinstance(value, list) and value else value
            )
    return df


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


def _image_to_bytes(image, fmt="PNG", dpi=150):
    buffer = BytesIO()
    save_kwargs = {}
    if fmt.upper() == "TIFF":
        save_kwargs["compression"] = "tiff_deflate"
    save_kwargs["dpi"] = (dpi, dpi)
    image.save(buffer, format=fmt.upper(), **save_kwargs)
    buffer.seek(0)
    return buffer.getvalue()


def _image_to_data_uri(image, fmt="PNG"):
    import base64

    return f"data:image/{fmt.lower()};base64,{base64.b64encode(_image_to_bytes(image, fmt)).decode('ascii')}"


def _build_subtype_view_chart_data(data):
    df = _get_report_dataframe(data)
    if "primary_subtype" not in df.columns or df.empty:
        return []
    pie_data = (
        df.groupby("primary_subtype")
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )
    return [{"label": row["primary_subtype"], "count": int(row["count"])} for _, row in pie_data.iterrows()]


def _build_subtype_view_image(data, dpi=150):
    items = _build_subtype_view_chart_data(data)
    scale = max(float(dpi), 1) / 150.0
    width = int(1600 * scale)
    legend_row_height = int(60 * scale)
    height = max(int(1000 * scale), int(285 * scale) + len(items) * legend_row_height)
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    title_font = _load_font(int(34 * scale), bold=True)
    body_font = _load_font(int(20 * scale))
    small_font = _load_font(int(18 * scale))

    pad = int(80 * scale)
    draw.text((pad, int(50 * scale)), "Subtype View", font=title_font, fill="#0f172a")

    if not items:
        draw.text((pad, int(180 * scale)), "No subtype data available", font=body_font, fill="#64748b")
        return img

    total = sum(item["count"] for item in items)
    color_map = _build_subtype_color_map([item["label"] for item in items])
    colors = [color_map.get(item["label"], SUBTYPE_PALETTE[0]) for item in items]

    pie_box = (pad, int(180 * scale), int(820 * scale), int(920 * scale))
    start_angle = -90
    for idx, item in enumerate(items):
        sweep = 360 * item["count"] / total if total else 0
        if sweep > 0:
            draw.pieslice(pie_box, start=start_angle, end=start_angle + sweep, fill=colors[idx], outline="white")
        start_angle += sweep
    draw.ellipse(pie_box, outline="#e2e8f0", width=3)

    legend_x = int(900 * scale)
    legend_y = int(200 * scale)
    draw.text((legend_x, int(150 * scale)), "Subtype distribution", font=body_font, fill="#0f172a")
    for idx, item in enumerate(items):
        y = legend_y + idx * int(60 * scale)
        draw.rounded_rectangle((legend_x, y, legend_x + int(30 * scale), y + int(30 * scale)), radius=int(8 * scale), fill=colors[idx])
        label = f"{item['label']} ({item['count']}, {round(100 * item['count'] / total)}%)"
        draw.text((legend_x + int(44 * scale), y + int(3 * scale)), label, font=small_font, fill="#334155")

    return img


def _build_sample_view_chart_rows(data):
    df = _get_report_dataframe(data)
    if df.empty or "Samples" not in df.columns:
        return [], []

    if "confidence" in df.columns:
        # Ties on confidence are common in small cohorts; sort_values' default "quicksort"
        # isn't stable, so two samples sharing a score could land in a different relative
        # order between calls - breaking ties on Samples keeps this and the matching sort
        # in the other Sample View renderer reproducible and consistent with each other.
        sort_cols = ["confidence", "Samples"] if "Samples" in df.columns else ["confidence"]
        df = df.sort_values(sort_cols, ascending=True, kind="stable")

    available_cols = [col for col in SAMPLE_VIEW_METHOD_COLUMNS if col in df.columns]

    rows = []
    for _, row in df.iterrows():
        sample = row.get("Samples", "N/A")
        predictions = []
        for col in available_cols:
            value = row.get(col)
            if value is None or value == "" or value == "N/A" or (isinstance(value, float) and pd.isna(value)):
                continue
            method = (
                col.replace("details.", "")
                .replace("result_", "")
                .replace("_pred", "")
                .replace("_", " ")
                .upper()
            )
            predictions.append((method, str(value)))
        rows.append((sample, predictions))

    order = [sample for sample, _ in rows]
    return order, rows


def _build_sample_view_image(data, dpi=150):
    order, rows = _build_sample_view_chart_rows(data)
    scale = max(float(dpi), 1) / 150.0
    width = int(1600 * scale)
    predictions = []
    for _, preds in rows:
        for _, pred in preds:
            if pred not in predictions:
                predictions.append(pred)

    legend_columns = 4
    legend_rows = max(1, (len(predictions) + legend_columns - 1) // legend_columns)
    height = max(
        int(900 * scale),
        int(220 * scale) + len(rows) * int(42 * scale) + int(95 * scale) + legend_rows * int(38 * scale),
    )
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    title_font = _load_font(int(34 * scale), bold=True)
    body_font = _load_font(int(20 * scale))
    small_font = _load_font(int(18 * scale))

    pad = int(80 * scale)
    draw.text((pad, int(50 * scale)), "Sample View", font=title_font, fill="#0f172a")

    if not rows:
        draw.text((pad, int(180 * scale)), "No sample data available", font=body_font, fill="#64748b")
        return img

    color_map = _build_subtype_color_map(predictions)

    bar_x0 = int(320 * scale)
    bar_x1 = width - int(260 * scale)
    bar_width = bar_x1 - bar_x0
    bar_top = int(180 * scale)
    row_height = int(38 * scale)

    for idx, (sample, preds) in enumerate(rows):
        y = bar_top + idx * row_height
        sample_label = str(sample)
        if len(sample_label) > 30:
            sample_label = sample_label[:27] + "..."
        draw.text((pad, y + int(3 * scale)), sample_label, font=small_font, fill="#334155")
        counts = Counter(pred for _, pred in preds)
        total = sum(counts.values()) or 1
        cursor = bar_x0
        draw.rounded_rectangle((bar_x0, y, bar_x1, y + int(24 * scale)), radius=int(10 * scale), outline="#e2e8f0", width=max(1, int(2 * scale)))
        for pred, count in counts.items():
            seg_width = max(3, round(bar_width * (count / total)))
            seg_end = min(bar_x1, cursor + seg_width)
            draw.rectangle((cursor, y, seg_end, y + int(24 * scale)), fill=color_map[pred])
            cursor = seg_end

    legend_y = bar_top + len(rows) * row_height + int(25 * scale)
    draw.text((pad, legend_y), "Prediction legend", font=body_font, fill="#0f172a")
    legend_y += int(42 * scale)
    for idx, pred in enumerate(predictions):
        row = idx // 4
        col = idx % 4
        x = pad + col * int(360 * scale)
        y = legend_y + row * int(38 * scale)
        draw.rounded_rectangle((x, y, x + int(24 * scale), y + int(24 * scale)), radius=int(6 * scale), fill=color_map[pred])
        draw.text((x + int(34 * scale), y + int(2 * scale)), pred, font=small_font, fill="#334155")

    return img


def _build_graphic_image(graphic_name, data, dpi=150):
    if graphic_name == "subtype":
        return _build_subtype_view_image(data, dpi=dpi)
    if graphic_name == "sample":
        return _build_sample_view_image(data, dpi=dpi)
    raise ValueError(f"Unknown graphic name: {graphic_name}")


def build_graphic_export_bytes(data, graphic_name, export_format="png", dpi=150):
    image = _build_graphic_image(graphic_name, data, dpi=dpi)
    fmt = export_format.lower()

    if fmt in ("png", "tiff"):
        return _image_to_bytes(image, fmt.upper(), dpi=dpi)

    if fmt == "pdf":
        try:
            from reportlab.lib.pagesizes import landscape, letter
            from reportlab.lib.units import inch
            from reportlab.platypus import Image as RLImage, Paragraph, SimpleDocTemplate, Spacer, PageBreak
            from reportlab.lib.styles import getSampleStyleSheet
        except Exception as exc:
            raise RuntimeError(f"PDF export dependencies are not available: {exc}") from exc

        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=landscape(letter),
            rightMargin=24,
            leftMargin=24,
            topMargin=24,
            bottomMargin=24,
        )
        styles = getSampleStyleSheet()
        title_style = styles["Title"]
        body_style = styles["BodyText"]
        story = [
            Paragraph("Multi-Method Subtyping Report", title_style),
            Spacer(1, 0.15 * inch),
            Paragraph("Graphics export", body_style),
            Spacer(1, 0.2 * inch),
        ]
        img_buffer = BytesIO(_image_to_bytes(image, "PNG", dpi=dpi))
        chart = RLImage(img_buffer)
        max_width = doc.width
        # Size against the space actually left after the title/subtitle block above,
        # not a fixed fraction of the whole page - see the matching fix and comment in
        # scripts/clinical_association.py's own PDF export for why.
        # See the matching fix in scripts/clinical_association.py's PDF export: wrap() alone
        # under-counts by the Title/BodyText styles' collapsed spaceBefore/spaceAfter margins,
        # so this leaves real headroom instead of cutting it to the wrap()-reported total.
        header_height = sum(flowable.wrap(doc.width, doc.height)[1] for flowable in story)
        max_height = doc.height - header_height - 30
        scale = min(max_width / chart.imageWidth, max_height / chart.imageHeight)
        chart.drawWidth = chart.imageWidth * scale
        chart.drawHeight = chart.imageHeight * scale
        story.extend([chart, PageBreak()])
        doc.build(story)
        pdf_bytes = buffer.getvalue()
        buffer.close()
        return pdf_bytes

        raise ValueError(f"Unsupported export format: {export_format}")


def _sort_report_data(data, sort_field="default", sort_order="asc"):
    reverse = str(sort_order).lower() == "desc"

    def sort_key(entry):
        if sort_field == "final_consensus":
            return str(_get_value(entry, "primary_subtype", "Uncertain")).lower()
        if sort_field == "agreement_score":
            try:
                return float(entry.get("confidence", 0) or 0)
            except Exception:
                return 0.0
        return str(_get_value(entry, "Samples", "N/A")).lower()

    return sorted(data, key=sort_key, reverse=reverse)


RESULTS_PAGE_SIZE = 100          # rows rendered at once; a full cohort is far too heavy for the browser


def _build_results_table(data, sort_field="default", sort_order="asc", page=0):
    """One page of the per-sample table. Rendering every sample at once produced ~60,000
    React components for a 1,000-sample cohort (3.4 MB of JSON), which blocks the browser's
    main thread for minutes: the server answers quickly, the page just never finishes
    painting. Only RESULTS_PAGE_SIZE rows are built, with a pager underneath."""
    sorted_data = _sort_report_data(data, sort_field=sort_field, sort_order=sort_order)
    method_groups = _available_result_method_groups(sorted_data)
    total = len(sorted_data)
    n_pages = max(1, (total + RESULTS_PAGE_SIZE - 1) // RESULTS_PAGE_SIZE)
    page = max(0, min(int(page or 0), n_pages - 1))
    first = page * RESULTS_PAGE_SIZE
    page_data = sorted_data[first:first + RESULTS_PAGE_SIZE]

    table_header = [
        html.Thead(html.Tr(
            [html.Th("Sample ID", className="ps-3")]
            + [html.Th(group["label"]) for group in method_groups]
            + [
                html.Th(_sortable_header("Final Consensus", "final_consensus", sort_field, sort_order, "final-consensus-info-icon"), className="text-primary"),
                html.Th(_sortable_header("Agreement Score", "agreement_score", sort_field, sort_order, "agreement-score-info-icon"), className="pe-3"),
            ],
            className="table-light"
        ))
    ]

    rows = []
    for entry in page_data:
        def get_val(key):
            return _get_value(entry, key)

        conf_pct = int(float(entry.get("confidence", 0)) * 100)
        primary = get_val("primary_subtype")
        badge_color = "danger" if primary == "Uncertain" else "primary"

        method_cells = [
            html.Td(_method_group_cell(entry, group["id"]), className="align-middle")
            for group in method_groups
        ]

        rows.append(html.Tr(
            [html.Td(entry.get("Samples", "N/A"), className="ps-3 fw-bold align-middle")]
            + method_cells
            + [
                html.Td(dbc.Badge(primary, color=badge_color, pill=True, className="px-3"), className="align-middle fw-bold"),
                html.Td([
                    dbc.Progress(
                        value=conf_pct,
                        label=f"{conf_pct}%",
                        color="danger" if conf_pct < 33 else "warning" if conf_pct < 66 else "success",
                        style={"height": "18px", "width": "100px"}
                    )
                ], className="align-middle pe-3"),
            ]
        ))

    table = dbc.Table(
        table_header + [html.Tbody(rows)],
        hover=True,
        striped=True,
        responsive=True,
        className="bg-white shadow-sm rounded border mb-0",
    )
    last = min(first + RESULTS_PAGE_SIZE, total)
    page_label = f"Showing {first + 1}-{last} of {total} samples" + (f"  ·  page {page + 1} of {n_pages}" if n_pages > 1 else "")
    # The Previous/Next buttons are kept in the DOM even on a single page (just
    # disabled): they are Inputs of the same callback that also handles the sort
    # buttons, and Dash only fires a callback when every one of its Input
    # components is currently rendered. Swapping them out for plain text here
    # silently broke sorting for any study with <= RESULTS_PAGE_SIZE samples.
    pager = dbc.Row(
        [
            dbc.Col(
                html.Small(page_label, className="text-muted"),
                className="align-self-center",
            ),
            dbc.Col(
                dbc.ButtonGroup([
                    dbc.Button("Previous", id="results-page-prev", size="sm", outline=True,
                               color="secondary", disabled=(page == 0)),
                    dbc.Button("Next", id="results-page-next", size="sm", outline=True,
                               color="secondary", disabled=(page >= n_pages - 1)),
                ]),
                className="text-end",
            ),
        ],
        className="mt-2 mb-1 px-1",
    )
    return html.Div([table, pager])


def _report_tumor_key_for_weighting(output_dir, resolved_label=None):
    """Raw tumour key of the run (e.g. 'luad', 'brca_pam50') as written by merge.R in
    report_metadata.json; falls back to the formatted label in lower case."""
    try:
        with open(os.path.join(output_dir, "report_metadata.json"), "r") as f:
            raw = str((json.load(f) or {}).get("tumor_type", "")).strip().lower()
        if raw:
            return raw
    except Exception:
        pass
    return str(resolved_label or "").strip().lower()


def _resolve_run_tumor_type(output_dir, tumor_type=None):
    current = format_tumor_type(tumor_type)
    if current != "Unknown" and current != "N/A":
        return current

    metadata_path = os.path.join(output_dir, "report_metadata.json")
    if os.path.exists(metadata_path):
        try:
            with open(metadata_path, "r") as f:
                metadata = json.load(f)
            metadata_tumor = format_tumor_type(metadata.get("tumor_type"))
            if metadata_tumor != "Unknown":
                return metadata_tumor
        except Exception:
            pass

    html_candidates = [
        os.path.join(output_dir, "report.html"),
        os.path.join(output_dir, "Subtyping_Clean_Report.html"),
    ]
    for html_path in html_candidates:
        if not os.path.exists(html_path):
            continue
        try:
            with open(html_path, "r", encoding="utf-8", errors="ignore") as f:
                html_text = f.read()
            match = re.search(r"Tumor type:\s*([^<·|]+)", html_text, re.IGNORECASE)
            if match:
                parsed = format_tumor_type(match.group(1).strip())
                if parsed != "Unknown":
                    return parsed
        except Exception:
            pass

    return "Unknown"


def _build_pdf_rows(data):
    method_groups = _available_result_method_groups(data)
    rows = [["Sample ID"] + [group["label"] for group in method_groups] + ["Final Consensus", "Agreement"]]
    for entry in data:
        conf_pct = int(float(entry.get("confidence", 0)) * 100)
        rows.append([
            str(_get_value(entry, "Samples", "N/A"))
        ] + [
            _method_group_text(entry, group["id"]) for group in method_groups
        ] + [
            str(_get_value(entry, "primary_subtype", "Uncertain")),
            f"{conf_pct}%",
        ])
    return rows


def _paragraphize_pdf_table(rows, header_style, cell_style, paragraph_cls):
    paragraph_rows = []
    for row_idx, row in enumerate(rows):
        style = header_style if row_idx == 0 else cell_style
        paragraph_rows.append([
            paragraph_cls(str(cell).replace("\n", "<br/>"), style)
            for cell in row
        ])
    return paragraph_rows


def build_pdf_report_bytes(output_dir, tumor_type="N/A", clinical_image_overrides=None):
    try:
        from io import BytesIO
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import landscape
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib.utils import ImageReader
        from reportlab.platypus import (
            BaseDocTemplate, PageTemplate, Frame, NextPageTemplate,
            Table, TableStyle, Paragraph, Spacer, PageBreak, KeepTogether, Image as RLImage,
        )
    except Exception as exc:
        raise RuntimeError(f"PDF generation dependencies are not available: {exc}") from exc

    json_path = os.path.join(output_dir, "dashboard_data.json")
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"Data file not found at {json_path}")

    with open(json_path, "r") as f:
        data = json.load(f)
    clinical_image_overrides = clinical_image_overrides or {}

    buffer = BytesIO()
    page_width, page_height = landscape(letter)
    # BaseDocTemplate (not SimpleDocTemplate) so each section can run under
    # its own named PageTemplate - see the addPageTemplates() call below -
    # giving every page in that section the matching running header
    # ("Subtype View", "Sample View", ...) for as many pages as that
    # section actually needs, without hardcoding page numbers.
    doc = BaseDocTemplate(
        buffer,
        pagesize=(page_width, page_height),
        rightMargin=20,
        leftMargin=20,
        topMargin=58,
        bottomMargin=52,
    )

    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    title_style.textColor = colors.HexColor("#0f172a")
    title_style.alignment = TA_LEFT
    body_style = ParagraphStyle(
        "BodySmall",
        parent=styles["BodyText"],
        fontSize=9,
        leading=11,
        textColor=colors.HexColor("#334155"),
    )
    small_style = ParagraphStyle(
        "Tiny",
        parent=styles["BodyText"],
        fontSize=7,
        leading=8,
        textColor=colors.HexColor("#475569"),
    )
    table_header_style = ParagraphStyle(
        "TableHeader",
        parent=styles["BodyText"],
        fontSize=6.3,
        leading=7.2,
        textColor=colors.HexColor("#0f172a"),
        fontName="Helvetica-Bold",
        wordWrap="CJK",
    )
    table_cell_style = ParagraphStyle(
        "TableCell",
        parent=styles["BodyText"],
        fontSize=5.8,
        leading=6.8,
        textColor=colors.HexColor("#334155"),
        wordWrap="CJK",
    )

    resolved_tumor_type = _resolve_run_tumor_type(output_dir, tumor_type)
    story = [
        Paragraph("Multi-Method Subtyping Report", title_style),
        Spacer(1, 0.15 * inch),
        Paragraph(
            f"Tumor type: {resolved_tumor_type}  |  Project: {os.path.basename(output_dir)}  |  Samples: {len(data)}",
            body_style,
        ),
        Spacer(1, 0.15 * inch),
    ]

    table_data = _paragraphize_pdf_table(_build_pdf_rows(data), table_header_style, table_cell_style, Paragraph)
    col_width_ratios = [0.13, 0.075, 0.075, 0.12, 0.17, 0.135, 0.10, 0.13, 0.065]
    col_widths = [doc.width * ratio for ratio in col_width_ratios]
    pdf_table = Table(table_data, colWidths=col_widths, repeatRows=1, splitByRow=1)
    pdf_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))

    story.append(pdf_table)
    subtype_img = _build_subtype_view_image(data)
    sample_img = _build_sample_view_image(data)

    sigmar_logo_path = _logo_path("sigmar_logo.png")

    def draw_scaled_logo(canvas, path, x, y, max_width, max_height):
        if not os.path.exists(path):
            return
        image = ImageReader(path)
        iw, ih = image.getSize()
        if iw <= 0 or ih <= 0:
            return
        scale = min(max_width / iw, max_height / ih)
        width = iw * scale
        height = ih * scale
        canvas.drawImage(image, x, y, width=width, height=height, mask="auto")

    def make_page_decorator(header_text):
        # One decorator per section (see addPageTemplates below) - draws
        # that section's running header at the top of every page it's
        # used on, plus the shared footer (logo + page number).
        def add_page_decorations(canvas, doc_obj):
            canvas.saveState()
            canvas.setFont("Helvetica-Bold", 9)
            canvas.setFillColor(colors.HexColor("#0F766E"))
            canvas.drawString(doc_obj.leftMargin, page_height - 0.5 * inch, header_text.upper())

            canvas.setStrokeColor(colors.HexColor("#cbd5e1"))
            canvas.setLineWidth(0.6)
            canvas.line(doc_obj.leftMargin, page_height - 0.78 * inch, page_width - doc_obj.rightMargin, page_height - 0.78 * inch)
            canvas.line(doc_obj.leftMargin, 0.88 * inch, page_width - doc_obj.rightMargin, 0.88 * inch)

            # Footer: SigMaR logo bottom-left, page number bottom-right.
            draw_scaled_logo(
                canvas,
                sigmar_logo_path,
                doc_obj.leftMargin,
                0.24 * inch,
                1.45 * inch,
                0.46 * inch,
            )
            canvas.setFont("Helvetica", 8)
            canvas.setFillColor(colors.HexColor("#475569"))
            canvas.drawRightString(
                page_width - doc_obj.rightMargin,
                0.4 * inch,
                f"Page {canvas.getPageNumber()}",
            )
            canvas.restoreState()
        return add_page_decorations

    main_frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main")
    doc.addPageTemplates([
        PageTemplate(id="TableView", frames=[main_frame], onPage=make_page_decorator("Multi-Method Subtyping Report")),
        PageTemplate(id="SubtypeView", frames=[main_frame], onPage=make_page_decorator("Subtype View")),
        PageTemplate(id="SampleView", frames=[main_frame], onPage=make_page_decorator("Sample View")),
        PageTemplate(id="ClinicalAssociation", frames=[main_frame], onPage=make_page_decorator("Clinical Association")),
    ])

    chart_sections = [
        ("Subtype View", "SubtypeView", subtype_img),
        ("Sample View", "SampleView", sample_img),
    ]

    # Reserved vertical space for the title+spacer above each chart, so
    # max_height leaves room for it on the SAME page instead of sizing the
    # chart against the full page and pushing the title (or the chart) onto
    # its own page. KeepTogether below is the actual guarantee - this
    # sizing just makes the common case fit without needing it.
    title_block_height = 0.5 * inch

    for section_title, template_id, pil_image in chart_sections:
        img_buffer = BytesIO(_image_to_bytes(pil_image, "PNG"))
        chart = RLImage(img_buffer)
        max_width = doc.width
        max_height = doc.height - title_block_height
        scale = min(max_width / chart.imageWidth, max_height / chart.imageHeight)
        chart.drawWidth = chart.imageWidth * scale
        chart.drawHeight = chart.imageHeight * scale
        story.append(NextPageTemplate(template_id))
        story.append(PageBreak())
        story.append(KeepTogether([
            Paragraph(section_title, title_style),
            Spacer(1, 0.12 * inch),
            chart,
        ]))

    clinical_summary = _load_clinical_association_summary(output_dir)
    if clinical_summary:
        try:
            from scripts.clinical_association import build_clinical_association_export_bytes
        except Exception:
            build_clinical_association_export_bytes = None

        story.append(NextPageTemplate("ClinicalAssociation"))
        story.append(PageBreak())
        story.append(Paragraph("Clinical Association", title_style))
        story.append(Spacer(1, 0.1 * inch))
        story.append(Paragraph("Association results generated from the study clinical variables.", body_style))
        story.append(Spacer(1, 0.12 * inch))

        for item in clinical_summary:
            stats_line = (
                f"Statistics unavailable: {item['error']}" if item.get("error")
                else f"Method: {item.get('method', 'n/a')} | p-value: {item.get('p_value', 'n/a')}"
            )
            header_block = [
                Paragraph(str(item.get("clinical_var", "Unknown")), styles["Heading2"]),
                Spacer(1, 0.06 * inch),
                Paragraph(stats_line, body_style),
                Spacer(1, 0.08 * inch),
            ]

            chart = None
            fallback_table = None
            if build_clinical_association_export_bytes is not None:
                try:
                    clinical_var = str(item.get("clinical_var", "Unknown"))
                    payload = clinical_image_overrides.get(clinical_var)
                    if payload is None:
                        static_image_name = item.get("data_static_image") or item.get("static_image_300dpi")
                        static_image_path = (
                            os.path.join(output_dir, "clinical_association", static_image_name)
                            if static_image_name else
                            os.path.join(
                                output_dir,
                                "clinical_association",
                                "img",
                                f"{re.sub(r'[^a-z0-9]+', '_', str(item.get('clinical_var', 'clinical_association')).lower()).strip('_') or 'clinical_association'}_static_data.png",
                            )
                        )
                        payload = build_clinical_association_export_bytes(
                            item,
                            export_format="png",
                            dpi=300,
                            static_image_path=static_image_path,
                        )
                    chart = RLImage(BytesIO(payload))
                except Exception:
                    fallback_rows = [["Metric", "Value"]]
                    fallback_rows.extend([
                        ["Method", str(item.get("method", "n/a"))],
                        ["Analysis kind", str(item.get("analysis_kind", "n/a"))],
                        ["p-value", str(item.get("p_value", "n/a"))],
                        ["Samples", str(item.get("total_samples", "n/a"))],
                        ["Subtype", str(item.get("clinical_var", "Unknown"))],
                    ])
                    fallback_table = Table(fallback_rows, repeatRows=1)
                    fallback_table.setStyle(TableStyle([
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eff6ff")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 7),
                        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]))

            stat_table = None
            if item.get("analysis_kind") == "continuous":
                stat_rows = [["Subtype", "Mean", "Median", "Std dev", "N"]]
                for cell in item.get("median_records", []) or []:
                    stat_rows.append([
                        str(cell.get("subtype", "Unknown")),
                        f"{float(cell.get('mean', 0.0)):.3f}" if cell.get("mean") is not None else "n/a",
                        f"{float(cell.get('median', 0.0)):.3f}" if cell.get("median") is not None else "n/a",
                        f"{float(cell.get('std', 0.0)):.3f}" if cell.get("std") is not None else "n/a",
                        str(cell.get("n", "n/a")),
                    ])
                stat_table = Table(stat_rows, repeatRows=1)
                stat_table.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eff6ff")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]))

            body_flowables = []
            if chart is not None and stat_table is not None:
                # Both a chart and a stat table for this variable (continuous
                # case) - side by side, table left / chart right, instead of
                # stacked one above the other.
                gap = 0.2 * inch
                left_width = doc.width * 0.40
                right_width = doc.width - left_width - gap
                max_height = doc.height * 0.65
                scale = min(right_width / chart.imageWidth, max_height / chart.imageHeight)
                chart.drawWidth = chart.imageWidth * scale
                chart.drawHeight = chart.imageHeight * scale
                left_cell = [Paragraph("Statistic summaries", body_style), Spacer(1, 0.06 * inch), stat_table]
                side_by_side = Table([[left_cell, chart]], colWidths=[left_width, right_width])
                side_by_side.setStyle(TableStyle([
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (0, 0), 0),
                    ("RIGHTPADDING", (0, 0), (0, 0), gap),
                    ("LEFTPADDING", (1, 0), (1, 0), 0),
                    ("RIGHTPADDING", (1, 0), (1, 0), 0),
                ]))
                body_flowables.append(side_by_side)
            elif chart is not None:
                max_width = doc.width
                max_height = doc.height * 0.74
                scale = min(max_width / chart.imageWidth, max_height / chart.imageHeight)
                chart.drawWidth = chart.imageWidth * scale
                chart.drawHeight = chart.imageHeight * scale
                body_flowables.append(chart)
            else:
                if fallback_table is not None:
                    body_flowables.append(fallback_table)
                if stat_table is not None:
                    body_flowables += [
                        Spacer(1, 0.12 * inch),
                        Paragraph("Statistic summaries", body_style),
                        Spacer(1, 0.06 * inch),
                        stat_table,
                    ]

            # Keep the variable's title with its chart/table on the same
            # page where it fits; only falls back to a page break if the
            # combined block genuinely can't fit on one page.
            story.append(KeepTogether(header_block + body_flowables))
            story.append(PageBreak())

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def build_html_report(output_dir, tumor_type="N/A"):
    json_path = os.path.join(output_dir, "dashboard_data.json")

    if not os.path.exists(json_path):
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Subtyping Report</title>
  <style>
    body {{ font-family: Arial, sans-serif; padding: 40px; color: #334155; }}
    .alert {{ padding: 16px; border: 1px solid #fecaca; background: #fef2f2; color: #991b1b; border-radius: 8px; }}
  </style>
</head>
<body>
  <div class="alert">Data file not found at {html_lib.escape(json_path)}</div>
</body>
</html>"""

    with open(json_path, "r") as f:
        data = json.load(f)

    resolved_tumor_type = _resolve_run_tumor_type(output_dir, tumor_type)
    report_subtype_color_map = _load_clinical_association_color_map(output_dir) or None
    method_groups = _available_result_method_groups(data)
    method_headers_html = "\n".join(
        f'<th data-sort="text">{html_lib.escape(group["label"])}<span class="sort-indicator"></span></th>'
        for group in method_groups
    )

    rows_html = []
    for entry in data:
        conf_pct = int(float(entry.get("confidence", 0)) * 100)
        primary = str(_get_value(entry, "primary_subtype", "Uncertain"))
        badge_class = "danger" if primary == "Uncertain" else "primary"
        conf_class = "danger" if conf_pct < 33 else "warning" if conf_pct < 66 else "success"
        method_cells_html = "".join(
            "<td>"
            + "<br>".join(
                html_lib.escape(line) for line in _method_group_text(entry, group["id"]).splitlines()
            )
            + "</td>"
            for group in method_groups
        )

        tumor_style = style_dict_to_css(get_tumor_type_pill_style(resolved_tumor_type))
        tumor_pill = (
            f"<span class='tumor-pill' style='{tumor_style}'>{html_lib.escape(resolved_tumor_type)}</span>"
        )

        rows_html.append(
            "<tr>"
            f"<td class='sample'>{html_lib.escape(str(_get_value(entry, 'Samples', 'N/A')))}</td>"
            f"{method_cells_html}"
            f"<td><span class='badge {badge_class}'>{html_lib.escape(primary)}</span></td>"
            f"<td><div class='progress'><div class='bar {conf_class}' style='width:{conf_pct}%'>{conf_pct}%</div></div></td>"
            "</tr>"
        )

    rows_html = "\n".join(rows_html)
    sample_count = len(data)
    # Interactive Plotly charts (same figures as the live Results page -
    # _build_subtype_view_figure/_build_sample_view_figure), not the static
    # PNGs used in the PDF export (which can't be interactive). plotly.js
    # itself is loaded once via CDN in <head>, so every fig.to_html() call
    # here and in _clinical_association_html_section below passes
    # include_plotlyjs=False rather than each trying to load it again.
    report_subtype_color_map = _load_clinical_association_color_map(output_dir) or None
    subtype_fig = _build_subtype_view_figure(data, subtype_color_map=report_subtype_color_map)
    sample_fig = _build_sample_view_figure(data, subtype_color_map=report_subtype_color_map)
    subtype_chart_html = subtype_fig.to_html(full_html=False, include_plotlyjs=False, config={"displaylogo": False, "responsive": True})
    sample_chart_html = sample_fig.to_html(full_html=False, include_plotlyjs=False, config={"displaylogo": False, "responsive": True})
    sigmar_logo = _logo_data_uri("sigmar_logo.png")
    clinical_summary = _load_clinical_association_summary(output_dir)
    clinical_section_html = _clinical_association_html_section(output_dir, clinical_summary)
    sigmar_logo_html = f'<img class="hero-logo" src="{sigmar_logo}" alt="SigMaR">' if sigmar_logo else ""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Subtyping Report</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <script src="https://cdn.plot.ly/plotly-3.5.0.min.js"></script>
  <style>
    :root {{
      --bg: #f8fafc;
      --panel: #ffffff;
      --text: #0f172a;
      --muted: #64748b;
      --border: #e2e8f0;
      --primary: #2563eb;
      --danger: #dc2626;
      --success: #16a34a;
      --warning: #d97706;
      --light: #e2e8f0;
    }}
    body {{
      margin: 0;
      padding: 32px;
      background: var(--bg);
      color: var(--text);
      font-family: Arial, sans-serif;
    }}
    .shell {{
      max-width: 1200px;
      margin: 0 auto;
    }}
    .hero {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 24px;
      margin-bottom: 20px;
    }}
    .hero-head {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 20px;
    }}
    .title {{
      margin: 0 0 8px 0;
      font-size: 28px;
    }}
    .subtle {{
      color: var(--muted);
      margin: 0;
    }}
    .hero-logo {{
      height: 56px;
      width: auto;
      object-fit: contain;
      flex: 0 0 auto;
    }}
    .tumor-pill {{
      display: inline-block;
      padding: 6px 12px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0;
      line-height: 1;
      vertical-align: middle;
    }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-top: 18px;
    }}
    .metric {{
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 14px;
      background: #fdfdfd;
    }}
    .metric .label {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .metric .value {{
      font-size: 18px;
      font-weight: 700;
      margin-top: 6px;
    }}
    .table-toolbar {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin: 20px 0 10px;
    }}
    #results-table-search {{
      flex: 0 1 320px;
      padding: 9px 14px;
      border: 1px solid var(--border);
      border-radius: 8px;
      font-size: 14px;
      color: var(--text);
      background: var(--panel);
    }}
    #results-table-search:focus {{
      outline: 2px solid var(--primary);
      outline-offset: 1px;
    }}
    .table-count {{
      font-size: 13px;
      color: var(--muted);
      white-space: nowrap;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 10px;
      overflow: hidden;
    }}
    th, td {{
      border-bottom: 1px solid var(--border);
      padding: 12px;
      vertical-align: top;
      text-align: left;
      font-size: 14px;
    }}
    th {{
      background: #f1f5f9;
      color: #334155;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    th[data-sort] {{
      cursor: pointer;
      user-select: none;
    }}
    th[data-sort]:hover {{
      background: #e2e8f0;
    }}
    .sort-indicator {{
      display: inline-block;
      width: 1em;
      margin-left: 2px;
      opacity: 0.5;
    }}
    th.sort-asc .sort-indicator::after {{
      content: "▲";
      opacity: 1;
    }}
    th.sort-desc .sort-indicator::after {{
      content: "▼";
      opacity: 1;
    }}
    .sample {{
      font-weight: 700;
      color: var(--text);
    }}
    .badge {{
      display: inline-block;
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      color: #fff;
    }}
    .badge.primary {{ background: var(--primary); }}
    .badge.danger {{ background: var(--danger); }}
    .badge.light {{ background: var(--light); color: var(--text); }}
    .progress {{
      width: 120px;
      height: 18px;
      border-radius: 999px;
      background: #e5e7eb;
      overflow: hidden;
    }}
    .bar {{
      height: 100%;
      color: #fff;
      font-size: 11px;
      line-height: 18px;
      text-align: center;
      white-space: nowrap;
    }}
    .bar.success {{ background: var(--success); }}
    .bar.warning {{ background: var(--warning); }}
    .bar.danger {{ background: var(--danger); }}
    .mini {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
    }}
    .mini span {{
      color: #334155;
      font-weight: 700;
    }}
    .graphics {{
      margin-top: 24px;
      display: grid;
      gap: 20px;
    }}
    .graphic-card {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 20px;
    }}
    .graphic-card img {{
      width: 100%;
      height: auto;
      display: block;
    }}
    .graphic-card .plotly-graph-div {{
      width: 100% !important;
    }}
    .clinical-section {{
      margin-top: 28px;
      display: grid;
      gap: 20px;
    }}
    .clinical-card {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 20px;
    }}
    .clinical-grid {{
      display: grid;
      grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr);
      gap: 18px;
      align-items: start;
    }}
    .clinical-meta {{
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 10px;
    }}
    .clinical-table {{
      width: 100%;
      border-collapse: collapse;
    }}
    .clinical-table th,
    .clinical-table td {{
      border-bottom: 1px solid var(--border);
      padding: 8px 10px;
      font-size: 13px;
      text-align: left;
      vertical-align: top;
    }}
    .clinical-table th {{
      background: #ecfeff;
    }}
    .clinical-muted {{
      color: var(--muted);
      font-size: 12px;
    }}
    @media (max-width: 900px) {{
      .summary {{ grid-template-columns: 1fr; }}
      body {{ padding: 16px; }}
      table, thead, tbody, th, td, tr {{ display: block; }}
      thead {{ display: none; }}
      tr {{ border-bottom: 1px solid var(--border); }}
      td {{ border-bottom: none; }}
    }}
  </style>
</head>
<body>
    <div class="shell">
      <div class="hero">
        <div class="hero-head">
          <div>
            <h1 class="title">Multi-Method Subtyping Report</h1>
            <p class="subtle">Tumor type: {tumor_pill} · Project: {html_lib.escape(os.path.basename(output_dir))}</p>
          </div>
          <div>{sigmar_logo_html}</div>
        </div>
      <div class="summary">
        <div class="metric"><div class="label">Samples</div><div class="value">{sample_count}</div></div>
        <div class="metric"><div class="label">Output folder</div><div class="value">{html_lib.escape(os.path.basename(output_dir))}</div></div>
        <div class="metric"><div class="label">Report source</div><div class="value">dashboard_data.json</div></div>
      </div>
    </div>

    <div class="table-toolbar">
      <input type="search" id="results-table-search" placeholder="Search table...">
      <span id="results-table-count" class="table-count"></span>
    </div>
    <table id="results-table">
      <thead>
        <tr>
          <th data-sort="text">Sample ID<span class="sort-indicator"></span></th>
          {method_headers_html}
          <th data-sort="text">Final Consensus <span title="Subtype assigned by the classifier, based on the label supported by the different classification methods, using weighted voting.">i</span><span class="sort-indicator"></span></th>
          <th data-sort="number">Agreement Score <span title="Level of agreement among the classification methods. It is calculated as the total weight of the methods supporting the winning subtype divided by the total weight of all methods.">i</span><span class="sort-indicator"></span></th>
        </tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>
    <div class="graphics">
      <div class="graphic-card">
        <h2 class="title" style="font-size: 22px; margin-bottom: 8px;">Subtype View</h2>
        {subtype_chart_html}
      </div>
      <div class="graphic-card">
        <h2 class="title" style="font-size: 22px; margin-bottom: 8px;">Sample View</h2>
        {sample_chart_html}
      </div>
    </div>
    {clinical_section_html}
  </div>
  <script>
    (function() {{
      var table = document.getElementById("results-table");
      if (!table) return;
      var tbody = table.tBodies[0];
      var searchInput = document.getElementById("results-table-search");
      var countEl = document.getElementById("results-table-count");
      var allRows = Array.prototype.slice.call(tbody.rows);

      function updateCount() {{
        if (!countEl) return;
        var visible = allRows.filter(function(r) {{ return r.style.display !== "none"; }}).length;
        countEl.textContent = visible + " of " + allRows.length + " samples";
      }}

      if (searchInput) {{
        searchInput.addEventListener("input", function() {{
          var q = searchInput.value.trim().toLowerCase();
          allRows.forEach(function(row) {{
            var text = row.textContent.toLowerCase();
            row.style.display = (q === "" || text.indexOf(q) !== -1) ? "" : "none";
          }});
          updateCount();
        }});
      }}

      var headers = Array.prototype.slice.call(table.tHead.rows[0].cells);
      headers.forEach(function(th, colIndex) {{
        var sortType = th.getAttribute("data-sort");
        if (!sortType) return;
        th.addEventListener("click", function() {{
          var asc = !th.classList.contains("sort-asc");
          headers.forEach(function(h) {{ h.classList.remove("sort-asc", "sort-desc"); }});
          th.classList.add(asc ? "sort-asc" : "sort-desc");

          var rows = Array.prototype.slice.call(tbody.rows);
          rows.sort(function(a, b) {{
            var av = a.cells[colIndex] ? a.cells[colIndex].textContent.trim() : "";
            var bv = b.cells[colIndex] ? b.cells[colIndex].textContent.trim() : "";
            var result;
            if (sortType === "number") {{
              var an = parseFloat(av.replace("%", "")) || 0;
              var bn = parseFloat(bv.replace("%", "")) || 0;
              result = an - bn;
            }} else {{
              result = av.localeCompare(bv);
            }}
            return asc ? result : -result;
          }});
          rows.forEach(function(row) {{ tbody.appendChild(row); }});
        }});
      }});

      updateCount();
    }})();
  </script>
</body>
</html>"""


def render_report_layout(output_dir, tumor_type="N/A", study_name=None, active_tab="table"):
    json_path = os.path.join(output_dir, "dashboard_data.json")

    if not os.path.exists(json_path):
        return dbc.Container([dbc.Alert(f"Data file not found at {json_path}", color="danger")], className="mt-5")

    with open(json_path, "r") as f:
        data = json.load(f)

    resolved_tumor_type = _resolve_run_tumor_type(output_dir, tumor_type)
    report_subtype_color_map = _load_clinical_association_color_map(output_dir) or None
    # Consensus mode badge: "equal" (default) or "ds" (validated Dawid-Skene weighting, opt-in)
    consensus_mode = "equal"
    try:
        with open(os.path.join(output_dir, "report_metadata.json"), "r") as _f:
            consensus_mode = str((json.load(_f) or {}).get("consensus_mode", "equal")).lower()
    except Exception:
        consensus_mode = "equal"
    consensus_badge = dbc.Badge(
        "Weighted consensus" if consensus_mode == "ds" else "Equal-vote consensus",
        color="info" if consensus_mode == "ds" else "secondary",
        pill=True, className="ms-2 align-middle",
        title=("Weighting scheme validated by balanced hold-out on an independent cohort"
               if consensus_mode == "ds" else "Each method casts one equal vote"),
    )
    header = dbc.Card(
        dbc.CardBody(
            [
                dbc.Row(
                    [
                        dbc.Col(
                            [
                                html.H2("Multi-Method Subtyping Report", className="card-title fw-bold text-primary"),
                                html.H5(
                                    [
                                        html.Span(
                                            resolved_tumor_type,
                                            className="me-2 tumor-pill",
                                            style=get_tumor_type_pill_style(resolved_tumor_type),
                                        ),
                                        html.Span(
                                            f"Project: {study_name or os.path.basename(output_dir)}",
                                            className="text-muted small",
                                        ),
                                        consensus_badge,
                                    ]
                                ),
                            ],
                            width=8,
                        ),
                        dbc.Col(
                            [
                                dbc.Button(
                                    "← Back to Results",
                                    id={"type": "nav_btn", "index": "back_to_results_btn"},
                                    size="sm",
                                    style=get_button_style("mist"),
                                    className="me-2",
                                ),
                                dbc.ButtonGroup(
                                    [
                                        dbc.Button("Download CSV", id="btn-download-csv", size="sm", style=get_button_style("jade")),
                                        dbc.Button("Download PDF", id="btn-download-pdf", size="sm", style=get_button_style("coral")),
                                        dbc.Button("Download HTML", id="btn-download-html", size="sm", style=get_button_style("sunrise")),
                                        dbc.Button("Download ZIP", id="btn-download-folder", size="sm", style=get_button_style("seafoam")),
                                    ]
                                ),
                                dcc.Download(id="download-figure-wrapper"),
                                dcc.Download(id="download-csv-wrapper"),
                                dcc.Download(id="download-pdf-wrapper"),
                                dcc.Download(id="download-html-wrapper"),
                                dcc.Download(id="download-folder-wrapper"),
                                dcc.Download(id="ca-report-download-wrapper"),
                                dcc.Store(id="ca-native-download-status"),
                                dcc.Store(id="ca-rendered-images-store"),
                                dcc.Store(id="ca-rendered-export-store"),
                            ],
                            width=4,
                            className="text-end align-self-start",
                        ),
                    ]
                ),
            ]
        ),
        className="mb-4 shadow-sm border-0",
    )
    results_table = _build_results_table(data)

    weighting_card = _build_weighting_card(consensus_mode, _report_tumor_key_for_weighting(output_dir, resolved_tumor_type))
    return dbc.Container([
        dcc.Store(id="results-sort-state", data={"field": "default", "order": "asc"}),
        dcc.Store(id="results-page-state", data=0),
        html.Div([
            header,
            *([weighting_card] if weighting_card is not None else []),
            dbc.Tabs(
                [
                    dbc.Tab(
                        html.Div(results_table, id="results-table-wrapper"),
                        label="Table",
                        tab_id="table",
                        tabClassName="px-3",
                        labelClassName="fw-semibold",
                        activeTabClassName="fw-semibold",
                    ),
                    dbc.Tab(
                        html.Div([
                            _graphic_section(
                                "Subtype View",
                                "Distribution of samples across the predicted subtypes (final consensus), shown as percentage and count of the total cohort.",
                                _build_subtype_view_figure(data, subtype_color_map=report_subtype_color_map),
                                "#0F766E",
                                "subtype-view-dpi",
                            ),
                            _graphic_section(
                                "Sample View",
                                "Per-sample breakdown of subtype predictions from each classification method. Each subtype is color-coded, with multi-colored bars indicating disagreement between methods.",
                                _build_sample_view_figure(data, subtype_color_map=report_subtype_color_map),
                                "#0F766E",
                                "sample-view-dpi",
                            ),
                        ]),
                        label="Graphics",
                        tab_id="graphics",
                        tabClassName="px-3",
                        labelClassName="fw-semibold",
                        activeTabClassName="fw-semibold",
                    ),
                    dbc.Tab(
                        dcc.Loading(
                            html.Div(id="clinical-association-content", className="px-3 pt-3 pb-3"),
                            type="circle",
                        ),
                        label="Clinical Associations",
                        tab_id="clinical-association",
                        tabClassName="px-3",
                        labelClassName="fw-semibold",
                        activeTabClassName="fw-semibold",
                    ),
                ],
                id="report-tabs",
                active_tab=active_tab if active_tab in {"table", "graphics", "clinical-association"} else "table",
                className="mb-0",
            ),
            dbc.Tooltip(
                "Subtype assigned by the classifier, based on the label supported by the different classification methods, using weighted voting.",
                target="final-consensus-info-icon",
                placement="top",
            ),
            dbc.Tooltip(
                "Level of agreement among the classification methods. It is calculated as the total weight of the methods supporting the winning subtype divided by the total weight of all methods.",
                target="agreement-score-info-icon",
                placement="top",
            ),
        ], id="report-printable-area")
    ], fluid=True, className="py-4 bg-light")
