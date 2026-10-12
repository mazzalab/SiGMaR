import os
import re
import base64
import json
import shutil
import time

import dash
from dash import Input, Output, State, dcc, html, dash_table
import dash_bootstrap_components as dbc

from config import DEFAULT_OUTPUT_ROOT
from scripts.clinical_association import (
    _load_input_metadata,
    _normalize_sample_key,
    build_clinical_association_figures,
    build_clinical_association_export_bytes,
    persist_clinical_association_outputs,
    load_study_frames,
)
from scripts.function import read_table_headers, read_table_preview


def _decode_data_url(data_url):
    if not data_url or "," not in str(data_url):
        return None
    _, encoded = str(data_url).split(",", 1)
    return base64.b64decode(encoded)


def _clinical_static_png_name(clinical_var):
    slug = re.sub(r"[^a-z0-9]+", "_", str(clinical_var).lower()).strip("_") or "clinical_association"
    return f"{slug}_static_data.png"


def _list_result_studies():
    if not os.path.isdir(DEFAULT_OUTPUT_ROOT):
        return []
    studies = []
    for entry in os.listdir(DEFAULT_OUTPUT_ROOT):
        study_path = os.path.join(DEFAULT_OUTPUT_ROOT, entry)
        if not os.path.isdir(study_path):
            continue
        dashboard_path = os.path.join(study_path, "dashboard_data.json")
        report_path = os.path.join(study_path, "report.html")
        if os.path.exists(dashboard_path) or os.path.exists(report_path):
            studies.append(entry)
    studies.sort(key=lambda name: os.path.getmtime(os.path.join(DEFAULT_OUTPUT_ROOT, name)), reverse=True)
    return studies


def _clinical_file_path(study_name):
    if not study_name:
        return None
    candidate = os.path.join(DEFAULT_OUTPUT_ROOT, study_name, "annotation.csv")
    return candidate if os.path.exists(candidate) else None


def _build_dropdown_options(columns):
    return [{"label": str(col), "value": str(col)} for col in columns]


def _detect_sample_column(columns):
    if not columns:
        return None
    exact_matches = {
        "sample", "samples", "sample_id", "sampleid", "sample id", "sample name", "sample_name", "id"
    }
    for col in columns:
        normalized = str(col).strip().lower()
        if normalized in exact_matches:
            return str(col)
    for col in columns:
        if "sample" in str(col).strip().lower():
            return str(col)
    return str(columns[0])


def _write_input_metadata(output_dir, **updates):
    os.makedirs(output_dir, exist_ok=True)
    metadata_path = os.path.join(output_dir, "input_metadata.json")
    metadata = _load_input_metadata(output_dir)
    metadata.update({key: value for key, value in updates.items() if value is not None})
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)


def _sample_overlap_status(output_dir, clinical_path, sample_column):
    dashboard_path = os.path.join(output_dir, "dashboard_data.json")
    if not os.path.exists(dashboard_path) or not clinical_path or not sample_column:
        return None, 0, 0

    with open(dashboard_path, "r") as f:
        dashboard_data = json.load(f) or []
    result_keys = {
        _normalize_sample_key(entry.get("Samples"))
        for entry in dashboard_data
        if _normalize_sample_key(entry.get("Samples"))
    }
    clinical_df = read_table_preview(clinical_path, nrows=None)
    if sample_column not in clinical_df.columns:
        return None, 0, len(result_keys)

    clinical_keys = {
        _normalize_sample_key(value)
        for value in clinical_df[sample_column].tolist()
        if _normalize_sample_key(value)
    }
    overlap = len(result_keys & clinical_keys)
    return overlap, len(clinical_keys), len(result_keys)


def _save_uploaded_annotation(contents, filename, study_name):
    if not study_name:
        raise ValueError("Select a study before uploading a clinical file.")
    if not contents or "," not in str(contents):
        raise ValueError("Uploaded file content is missing.")

    study_dir = os.path.join(DEFAULT_OUTPUT_ROOT, study_name)
    if not os.path.isdir(study_dir):
        raise ValueError(f"Study folder not found: {study_name}")

    _, encoded = str(contents).split(",", 1)
    payload = base64.b64decode(encoded)
    if not payload:
        raise ValueError("Uploaded file is empty.")

    target_path = os.path.join(study_dir, "annotation.csv")
    previous_payload = None
    if os.path.exists(target_path):
        with open(target_path, "rb") as f:
            previous_payload = f.read()

    # Stage under the ORIGINAL extension first - read_table_preview/_is_xlsx
    # detect xlsx by content (zipfile signature), but openpyxl.load_workbook
    # itself validates the file's extension and rejects a real .xlsx payload
    # if it's sitting behind a ".csv" name. Parsing from a same-extension temp
    # file and re-writing as genuine CSV text avoids that mismatch regardless
    # of what format was actually uploaded (.xlsx/.xlsm/.csv/.tsv/...).
    _, ext = os.path.splitext(filename or "")
    staged_path = os.path.join(study_dir, f"_annotation_upload_staged{ext or '.csv'}")
    try:
        with open(staged_path, "wb") as f:
            f.write(payload)

        df = read_table_preview(staged_path, nrows=None)
        if df is None or df.empty or len(df.columns) == 0:
            raise ValueError("The uploaded clinical file does not contain a readable header row.")
        df.to_csv(target_path, index=False)

        headers = read_table_headers(target_path)
        if not headers:
            raise ValueError("The uploaded clinical file does not contain a readable header row.")
    except Exception:
        if previous_payload is not None:
            with open(target_path, "wb") as f:
                f.write(previous_payload)
        elif os.path.exists(target_path):
            os.remove(target_path)
        raise
    finally:
        if os.path.exists(staged_path):
            os.remove(staged_path)

    clinical_results_dir = os.path.join(study_dir, "clinical_association")
    shutil.rmtree(clinical_results_dir, ignore_errors=True)
    os.makedirs(os.path.join(clinical_results_dir, "img"), exist_ok=True)
    return target_path, headers


def _format_p_value(value):
    try:
        value = float(value)
    except Exception:
        return "n/a"
    if value < 0.001:
        return "< 0.001"
    return f"{value:.4f}"


def _build_posthoc_table(records, analysis_kind="categorical"):
    if not records:
        return html.Div(
            "No post hoc comparisons are available.",
            className="small text-muted",
        )

    def pvalue_sort_key(record):
        try:
            return (0, float(record.get("p_value")))
        except Exception:
            return (1, float("inf"))

    records = sorted(records, key=pvalue_sort_key)

    table_rows = []
    if analysis_kind == "continuous":
        effect_label = records[0].get("effect_label", "Effect")
        for cell in records:
            is_significant = float(cell.get("q_value", 1.0)) < 0.05
            table_rows.append(
                {
                    "Subtype A": cell.get("subtype_a", "Unknown"),
                    "Subtype B": cell.get("subtype_b", "Unknown"),
                    "Test": cell.get("test", "Mann-Whitney U"),
                    effect_label: f"{float(cell.get('effect', 0.0)):.3f}",
                    "p-value": f"{float(cell.get('p_value', 1.0)):.4g}",
                    "q-value (padj)": f"{float(cell.get('q_value', 1.0)):.4g}",
                    "__significant": "yes" if is_significant else "no",
                }
            )
        columns = [
            {"name": "Subtype A", "id": "Subtype A"},
            {"name": "Subtype B", "id": "Subtype B"},
            {"name": "Test", "id": "Test"},
            {"name": effect_label, "id": effect_label},
            {"name": "p-value", "id": "p-value"},
            {"name": "q-value (padj)", "id": "q-value (padj)"},
        ]
    else:
        for cell in records:
            is_significant = float(cell.get("q_value", 1.0)) < 0.05
            table_rows.append(
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

    return dash_table.DataTable(
        data=table_rows,
        columns=columns,
        hidden_columns=["__significant"],
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
            "backgroundColor": "#ecfdf5",
            "fontWeight": "700",
            "border": "1px solid #d1fae5",
        },
        style_data={
            "border": "1px solid #e5e7eb",
        },
        style_data_conditional=[
            {
                "if": {"filter_query": "{__significant} = 'yes'"},
                "fontWeight": "700",
                "backgroundColor": "#f0fdf4",
            }
        ],
    )


def _build_stats_block(clinical_var, stats):
    if stats.get("error"):
        return dbc.Card(
            dbc.CardBody([
                html.H6("Statistics", className="mb-2"),
                html.Div(f"Statistics unavailable for {clinical_var}.", className="fw-semibold"),
                html.Div(stats["error"], className="small mt-1"),
            ]),
            className="h-100 border-0 shadow-sm bg-light",
        )

    def _format_cell_line(cell):
        clinical_level = cell.get("clinical_level", "Unknown")
        subtype = cell.get("subtype", "Unknown")
        residual = float(cell.get("residual", 0.0))
        observed = int(cell.get("observed", 0))
        expected = float(cell.get("expected", 0.0))
        return html.Li(
            f"Clinical level {clinical_level} enriched for subtype {subtype} "
            f"(resid {residual:+.2f}, obs {observed}, exp {expected:.1f})",
            className="small",
        )

    p_raw = stats.get("p_value", None)
    try:
        p_raw = float(p_raw)
    except Exception:
        p_raw = None

    method = stats.get("method", "n/a")
    stat_label = stats.get("statistic_label", "Statistic")
    stat_value = stats.get("statistic_value", None)
    dof = stats.get("degrees_freedom", None)
    p_value = _format_p_value(p_raw)
    total_samples = stats.get("total_samples", 0)
    rows = stats.get("rows", 0)
    cols = stats.get("cols", 0)
    top_subtype = stats.get("top_enriched_subtype")
    analysis_kind = stats.get("analysis_kind", "categorical")

    details = [f"{stat_label}: {stat_value:.4f}" if isinstance(stat_value, (int, float)) else f"{stat_label}: n/a"]
    if dof is not None:
        details.append(f"df: {dof}")

    enriched_cells = stats.get("significant_cells", [])
    if not enriched_cells and p_raw is not None and p_raw < 0.05:
        enriched_cells = stats.get("top_positive_cells", [])[:5]

    return dbc.Card(
        dbc.CardBody([
            html.H6("Statistics", className="mb-2"),
            html.Div(
                [
                    html.Div([html.Span("Test", className="text-muted small"), html.Div(method, className="fw-semibold")], className="mb-2"),
                    html.Div([html.Span("p-value", className="text-muted small"), html.Div(p_value, className="fw-semibold")], className="mb-2"),
                    html.Div([html.Span("Samples", className="text-muted small"), html.Div(str(total_samples), className="fw-semibold")], className="mb-2"),
                    html.Div([html.Span("Table", className="text-muted small"), html.Div(f"{rows} x {cols}", className="fw-semibold")], className="mb-2") if analysis_kind == "categorical" else html.Div([html.Span("Subtype groups", className="text-muted small"), html.Div(str(stats.get("groups", 0)), className="fw-semibold")], className="mb-2"),
                    html.Div([html.Span("Top subtype", className="text-muted small"), html.Div(top_subtype or "n/a", className="fw-semibold")], className="mb-2"),
                    html.Div(" | ".join(details), className="small mt-2"),
                    html.Div(
                        "Fisher exact is used for 2x2 tables; otherwise chi-square is used."
                        if analysis_kind == "categorical"
                        else (
                            "Normality is checked with Shapiro. If all subtypes pass, the global test uses Welch t-test (2 groups) or ANOVA (>2 groups); otherwise Mann-Whitney U or Kruskal-Wallis is used."
                        ),
                        className="small text-muted mt-2",
                    ),
                    html.Hr(className="my-3"),
                    html.Div("Associated cells" if analysis_kind == "categorical" else "Subtype summary", className="fw-semibold mb-2"),
                    html.Ul(
                        [
                            _format_cell_line(cell)
                            for cell in enriched_cells[:5]
                        ],
                        className="mb-0 ps-3",
                    ) if (analysis_kind == "categorical" and p_raw is not None and p_raw < 0.05 and enriched_cells) else html.Div(
                        "Subtype summaries are saved in the clinical_association folder inside the output.",
                        className="small text-muted",
                    ),
                ]
            ),
        ]),
        className="h-100 border-0 shadow-sm bg-light",
    )


def register_callbacks_clinical_association(app):
    @app.callback(
        Output("ca_annotation_upload_status", "children"),
        Output("ca_annotation_upload_signal", "data"),
        Input("ca_annotation_upload", "contents"),
        State("ca_annotation_upload", "filename"),
        State("ca_study_select", "value"),
        prevent_initial_call=True,
    )
    def upload_replacement_annotation(contents, filename, selected_study):
        if not contents:
            return dash.no_update, dash.no_update
        try:
            _, headers = _save_uploaded_annotation(contents, filename, selected_study)
            return (
                dbc.Alert(
                    f"{filename or 'Clinical file'} saved as annotation.csv for {selected_study}. "
                    "Previous clinical association outputs were cleared; run the analysis again.",
                    color="success",
                    className="mb-0",
                ),
                {
                    "study": selected_study,
                    "filename": filename,
                    "columns": len(headers),
                    "ts": time.time(),
                },
            )
        except Exception as exc:
            return (
                dbc.Alert(f"Clinical file upload failed: {exc}", color="danger", className="mb-0"),
                dash.no_update,
            )

    @app.callback(
        [Output("ca_study_select", "options"),
         Output("ca_study_select", "value"),
         Output("ca_study_select", "disabled"),
         Output("ca_selected_study_label", "children"),
         Output("ca_clinical_vars_select", "options"),
         Output("ca_clinical_vars_select", "value"),
         Output("ca_clinical_vars_select", "disabled"),
         Output("ca_clinical_missing_banner", "children"),
         Output("ca_sample_column_select", "options"),
         Output("ca_sample_column_select", "value"),
         Output("ca_sample_column_select", "disabled"),
         Output("ca_sample_match_status", "children"),
         Output("ca_run_btn", "disabled"),
         Output({"type": "nav_btn", "index": "ca_results_btn"}, "disabled"),
         Output("selected_study_persistent", "data")],
        [Input("url", "pathname"),
         Input("ca_study_select", "value"),
         Input("ca_sample_column_select", "value"),
         Input("ca_annotation_upload_signal", "data")],
        prevent_initial_call=False
    )
    def refresh_clinical_association_view(pathname, selected_study, selected_sample_column, upload_signal):
        studies = _list_result_studies()
        if not studies:
            return (
                [], None, True, "No studies available in Results.",
                [], [], True,
                dbc.Alert(
                    "No studies are available in Results yet.",
                    color="warning",
                    className="mb-0",
                ),
                [], None, True, html.Div(),
                True, True, None,
            )

        options = [{"label": study, "value": study} for study in studies]
        active_study = selected_study if selected_study in studies else studies[0]
        selected_label = f"Selected study: {active_study}"

        clinical_path = _clinical_file_path(active_study)
        if not clinical_path:
            summary_path = os.path.join(DEFAULT_OUTPUT_ROOT, active_study, "clinical_association", "clinical_association_summary.json")
            results_ready = os.path.exists(summary_path) and os.path.getsize(summary_path) > 0
            return (
                options, active_study, False, selected_label,
                [], [], True,
                dbc.Alert(
                    "Clinical association cannot be run because clinical data are missing in the selected study output.",
                    color="warning",
                    className="mb-0",
                ),
                [], None, True, html.Div(),
                True, not results_ready, active_study,
            )

        try:
            clinical_columns = read_table_headers(clinical_path)
            sample_options = _build_dropdown_options(clinical_columns)
            metadata = _load_input_metadata(os.path.join(DEFAULT_OUTPUT_ROOT, active_study))
            clinical_sample_col = selected_sample_column if selected_sample_column in clinical_columns else metadata.get("clinical_sample_column")
            if clinical_sample_col not in clinical_columns:
                clinical_sample_col = _detect_sample_column(clinical_columns)

            output_dir = os.path.join(DEFAULT_OUTPUT_ROOT, active_study)
            _write_input_metadata(output_dir, clinical_sample_column=clinical_sample_col)
            overlap, clinical_sample_count, result_sample_count = _sample_overlap_status(
                output_dir,
                clinical_path,
                clinical_sample_col,
            )
            if overlap is None:
                sample_status = html.Div()
                has_sample_overlap = False
            elif overlap > 0:
                sample_status = dbc.Alert(
                    f"Sample match check: {overlap} overlapping samples found "
                    f"between the clinical file ({clinical_sample_count} sample IDs) and subtyping results ({result_sample_count} samples).",
                    color="success",
                    className="mb-0",
                )
                has_sample_overlap = True
            else:
                sample_status = dbc.Alert(
                    f"Sample match check failed: no overlapping samples found using column '{clinical_sample_col}'. "
                    "Select a different Sample ID column before running the analysis.",
                    color="danger",
                    className="mb-0",
                )
                has_sample_overlap = False

            clinical_var_columns = [str(col) for col in clinical_columns if str(col) != str(clinical_sample_col)]
            clinical_options = [{"label": str(col), "value": str(col)} for col in clinical_var_columns]
            default_values = clinical_var_columns[:1] if clinical_var_columns else []
            if not clinical_var_columns:
                return (
                    options, active_study, False, selected_label,
                    [], [], True,
                    dbc.Alert(
                        f"Clinical data loaded from {active_study}, but no clinical variables were found after the sample ID column.",
                        color="warning",
                        className="mb-0",
                    ),
                    sample_options, clinical_sample_col, False, sample_status,
                    True, True, active_study,
                )
            summary_path = os.path.join(DEFAULT_OUTPUT_ROOT, active_study, "clinical_association", "clinical_association_summary.json")
            results_ready = os.path.exists(summary_path) and os.path.getsize(summary_path) > 0
            return (
                options, active_study, False, selected_label,
                clinical_options, default_values, False,
                dbc.Alert(
                    f"Clinical data loaded from {active_study}.",
                    color="info",
                    className="mb-0",
                ),
                sample_options, clinical_sample_col, False, sample_status,
                True if not default_values or not has_sample_overlap else False,
                not results_ready,
                active_study,
            )
        except Exception as exc:
            summary_path = os.path.join(DEFAULT_OUTPUT_ROOT, active_study, "clinical_association", "clinical_association_summary.json")
            results_ready = os.path.exists(summary_path) and os.path.getsize(summary_path) > 0
            return (
                options, active_study, False, selected_label,
                [], [], True,
                dbc.Alert(
                    f"Error reading clinical data for {selected_study}: {exc}",
                    color="danger",
                    className="mb-0",
                ),
                [], None, True, html.Div(),
                True, not results_ready, active_study,
            )

    @app.callback(
        Output("ca_agreement_threshold", "disabled"),
        Input("ca_use_all_samples", "value"),
        prevent_initial_call=False
    )
    def toggle_agreement_threshold(use_all_values):
        return bool(use_all_values and "all" in use_all_values)

    app.clientside_callback(
        """
        async function(children) {
            if (!children || !window.Plotly) {
                return window.dash_clientside.no_update;
            }

            await new Promise((resolve) => setTimeout(resolve, 1000));

            const images = {};
            for (const node of document.querySelectorAll("[id]")) {
                let parsed = null;
                try {
                    parsed = JSON.parse(node.id);
                } catch (e) {
                    continue;
                }
                if (!parsed || parsed.type !== "ca_live_graph") {
                    continue;
                }

                const clinicalVar = String(parsed.clinical_var || "Unknown");
                const plot = node.classList && node.classList.contains("js-plotly-plot")
                    ? node
                    : node.querySelector(".js-plotly-plot");
                if (!plot) {
                    continue;
                }

                try {
                    const nativeOptions = Object.assign(
                        {},
                        (plot._context && plot._context.toImageButtonOptions) || {}
                    );
                    images[clinicalVar] = await window.Plotly.toImage(
                        plot,
                        Object.assign(nativeOptions, {format: "png"})
                    );
                } catch (e) {
                    images[clinicalVar] = null;
                }
            }

            if (!Object.keys(images).length) {
                return window.dash_clientside.no_update;
            }

            return {status: "captured", images: images, ts: Date.now()};
        }
        """,
        Output("ca-rendered-run-images-store", "data"),
        Input("ca_results_container", "children"),
        prevent_initial_call=True,
    )

    @app.callback(
        Output("ca_results_container", "children"),
        Input("ca_run_btn", "n_clicks"),
        State("ca_study_select", "value"),
        State("ca_clinical_vars_select", "value"),
        State("ca_agreement_threshold", "value"),
        State("ca_use_all_samples", "value"),
        State("ca_axis_orientation", "value"),
        running=[
            (Output("ca_run_btn", "disabled"), True, False),
            (Output({"type": "nav_btn", "index": "ca_results_btn"}, "disabled"), True, False),
        ],
        prevent_initial_call=True
    )
    def run_clinical_association(n_clicks, study_name, clinical_vars, agreement_threshold, use_all_values, orientation):
        if not n_clicks:
            return dash.no_update
        if not study_name or not clinical_vars:
            return dbc.Alert(
                "Please select a study and at least one clinical variable.",
                color="warning",
                className="mb-0",
            )

        output_dir = os.path.join(DEFAULT_OUTPUT_ROOT, study_name)
        use_all_samples = bool(use_all_values and "all" in use_all_values)
        threshold_value = agreement_threshold if agreement_threshold is not None else 70
        try:
            threshold = float(threshold_value) / 100.0
        except Exception:
            threshold = 0.7

        try:
            figures = build_clinical_association_figures(
                output_dir,
                clinical_vars,
                agreement_threshold=threshold,
                use_all_samples=use_all_samples,
                orientation=orientation or "subtype_x",
            )
            persist_clinical_association_outputs(
                output_dir,
                figures,
                study_name=study_name,
                analysis_config={
                    "study_name": study_name,
                    "agreement_threshold_pct": int(round(threshold * 100)),
                    "use_all_samples": use_all_samples,
                    "clinical_vars": list(clinical_vars),
                    "orientation": orientation or "subtype_x",
                },
            )
        except Exception as exc:
            return dbc.Alert(
                f"Error while building the clinical association analysis: {exc}",
                color="danger",
                className="mb-0",
            )

        if not figures:
            return dbc.Alert(
                "No clinical association plots could be generated with the current selection.",
                color="warning",
                className="mb-0",
            )

        merged, _, _ = load_study_frames(output_dir)
        if merged is None or merged.empty:
            return dbc.Alert(
                "Clinical association cannot be run because clinical data are missing in the selected study output.",
                color="warning",
                className="mb-0",
            )

        cards = []
        for clinical_var, fig, stats in figures:
            p_value = stats.get("p_value")
            try:
                p_value = float(p_value)
            except Exception:
                p_value = None

            posthoc_rows = []
            analysis_kind = stats.get("analysis_kind", "categorical")
            if p_value is not None and p_value < 0.05:
                posthoc_rows = stats.get("pairwise_cells", [])

            cards.append(
                dbc.Card(
                    dbc.CardBody([
                        html.H5(clinical_var, className="mb-3"),
                        dbc.Row([
                            dbc.Col(
                                dcc.Graph(
                                    id={"type": "ca_live_graph", "clinical_var": clinical_var},
                                    figure=fig,
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
                            dbc.Col(
                                _build_stats_block(clinical_var, stats),
                                md=3,
                                xs=12,
                            ),
                        ], className="g-3 align-items-stretch"),
                        html.Div(className="mt-3"),
                        html.Div("Post hoc table", className="fw-semibold mb-2"),
                        _build_posthoc_table(posthoc_rows, analysis_kind=analysis_kind) if posthoc_rows else html.Div(
                            "Post hoc table is available only when the global test is significant.",
                            className="small text-muted",
                        ),
                    ]),
                    className="shadow-sm border-0 mb-4",
                )
            )

        banner = dbc.Alert(
            f"Analysis generated from {study_name} using {'all samples' if use_all_samples else f'agreement score >= {int(threshold * 100)}%'}.",
            color="success",
            className="mb-3",
        )
        return [banner] + cards

    @app.callback(
        Output("ca-rendered-run-images-store", "clear_data"),
        Input("ca-rendered-run-images-store", "data"),
        State("ca_study_select", "value"),
        State("selected_study_persistent", "data"),
        prevent_initial_call=True
    )
    def persist_browser_rendered_clinical_images(rendered_images, study_name, selected_study):
        if not rendered_images or rendered_images.get("status") != "captured":
            return dash.no_update
        # Static clinical images are generated from data with matplotlib in
        # scripts/static_clinical_plots.py. Browser captures remain transient.
        return True

    @app.callback(
        Output("ca-download-wrapper", "data"),
        Input({"type": "ca_download_btn", "clinical_var": dash.ALL, "format": dash.ALL}, "n_clicks"),
        State("ca_study_select", "value"),
        State("selected_study_persistent", "data"),
        State("base_path_persistent", "data"),
        prevent_initial_call=True
    )
    def download_clinical_association_graph(n_clicks, study_name, selected_study, base_path):
        trig_id = dash.ctx.triggered_id
        if not trig_id:
            return dash.no_update
        if not n_clicks or not any((isinstance(click, (int, float)) and click > 0) for click in (n_clicks if isinstance(n_clicks, (list, tuple)) else [n_clicks])):
            return dash.no_update

        active_study = study_name or selected_study
        if not active_study:
            return dash.no_update

        output_dir = os.path.join(DEFAULT_OUTPUT_ROOT, active_study)
        summary_path = os.path.join(output_dir, "clinical_association", "clinical_association_summary.json")
        if not os.path.exists(summary_path):
            return dash.no_update

        import json

        with open(summary_path, "r") as f:
            summary = json.load(f) or []

        if not isinstance(summary, list):
            return dash.no_update

        clinical_var = trig_id.get("clinical_var")
        export_format = trig_id.get("format", "png")
        selected_item = None
        for item in summary:
            if str(item.get("clinical_var")) == str(clinical_var):
                selected_item = item
                break
        if not selected_item:
            return dash.no_update

        static_image_name = selected_item.get("data_static_image") or selected_item.get("static_image_300dpi")
        static_image_path = (
            os.path.join(output_dir, "clinical_association", static_image_name)
            if static_image_name else
            os.path.join(
                output_dir,
                "clinical_association",
                "img",
                f"{re.sub(r'[^a-z0-9]+', '_', str(clinical_var).lower()).strip('_') or 'clinical_association'}_static_data.png",
            )
        )

        payload = build_clinical_association_export_bytes(
            selected_item,
            export_format=export_format,
            dpi=300,
            static_image_path=static_image_path,
        )
        filename = f"{clinical_var}.{export_format.lower()}"
        return dcc.send_bytes(lambda buffer: buffer.write(payload), filename)
