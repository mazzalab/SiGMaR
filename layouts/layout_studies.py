import json
import os
import re
from datetime import datetime

from dash import html, dcc
import dash_bootstrap_components as dbc

from config import (
    DEFAULT_OUTPUT_ROOT, format_tumor_type, get_tumor_type_pill_style,
    get_button_style, is_sigmar_study_dir,
)


def get_study_dirs(output_root=DEFAULT_OUTPUT_ROOT):
    if not os.path.exists(output_root):
        return []
    studies = []
    for name in sorted(os.listdir(output_root)):
        full_path = os.path.join(output_root, name)
        # Only list directories that actually look like a SiGMaR study -
        # output_root can now be any folder the user picked (custom output
        # location), so an unfiltered listdir() would surface every
        # unrelated subfolder that happens to live there too.
        if os.path.isdir(full_path) and not name.startswith(".") and is_sigmar_study_dir(full_path):
            studies.append(name)
    return studies


def _parse_created_at(value):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except Exception:
            continue
    return datetime.min


def _load_study_metadata(output_root, study_name):
    study_path = os.path.join(output_root, study_name)
    metadata_path = os.path.join(study_path, "report_metadata.json")
    summary_path = os.path.join(study_path, "dashboard_data.json")
    final_path = os.path.join(study_path, "final_complete_summary.txt")
    html_candidates = [
        os.path.join(study_path, "report.html"),
        os.path.join(study_path, "Subtyping_Clean_Report.html"),
    ]

    metadata = {}
    if os.path.exists(metadata_path):
        try:
            with open(metadata_path, "r") as f:
                metadata = json.load(f)
        except Exception:
            metadata = {}

    total_pzt = metadata.get("total_pzt")
    if total_pzt is None:
        if os.path.exists(summary_path):
            try:
                with open(summary_path, "r") as f:
                    total_pzt = len(json.load(f))
            except Exception:
                total_pzt = None
        elif os.path.exists(final_path):
            try:
                with open(final_path, "r") as f:
                    total_pzt = max(sum(1 for _ in f) - 1, 0)
            except Exception:
                total_pzt = None

    created_at = metadata.get("report_created_at")
    if created_at is None:
        try:
            created_at = datetime.fromtimestamp(os.path.getmtime(summary_path if os.path.exists(summary_path) else study_path)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            created_at = "-"

    tumor_type = None
    for html_path in html_candidates:
        if os.path.exists(html_path):
            try:
                with open(html_path, "r", encoding="utf-8", errors="ignore") as f:
                    html_text = f.read()
                match = re.search(r"Tumor type:\s*([^<·|]+)", html_text, re.IGNORECASE)
                if match:
                    tumor_type = match.group(1).strip()
                    break
            except Exception:
                pass

    if not tumor_type:
        tumor_type = metadata.get("tumor_type", "Unknown")

    tumor_type = format_tumor_type(tumor_type)

    return {
        "study_name": study_name,
        "tumor_type": tumor_type,
        "total_pzt": total_pzt if total_pzt is not None else "-",
        "created_at": created_at,
    }


def get_study_records(output_root=DEFAULT_OUTPUT_ROOT):
    return [_load_study_metadata(output_root, study) for study in get_study_dirs(output_root)]

def _build_study_rows(records):
    rows = []
    for record in records:
        study = record["study_name"]
        rows.append(
            html.Tr([
                html.Td(study, className="fw-semibold align-middle"),
                html.Td(
                    html.Span(
                        record["tumor_type"],
                        className="tumor-pill",
                        style=get_tumor_type_pill_style(record["tumor_type"]),
                    ),
                    className="align-middle",
                ),
                html.Td(record["created_at"], className="align-middle"),
                html.Td(record["total_pzt"], className="align-middle"),
                html.Td([
                    dbc.Button(
                        "Open",
                        id={"type": "study_open_btn", "study": study},
                        size="sm",
                        n_clicks=0,
                        className="me-2",
                        style=get_button_style("jade"),
                    ),
                    dbc.Button(
                        "Download",
                        id={"type": "study_download_btn", "study": study},
                        size="sm",
                        n_clicks=0,
                        className="me-2",
                        style=get_button_style("seafoam"),
                    ),
                    dbc.Button(
                        "Delete",
                        id={"type": "study_delete_btn", "study": study},
                        size="sm",
                        n_clicks=0,
                        style=get_button_style("coral"),
                    ),
                ], className="align-middle text-end"),
            ])
        )
    return rows


def render_studies_table(records, empty_message=None):
    if not records:
        message = empty_message or "No saved studies found in uploads/results."
        return dbc.Alert(
            [
                html.H5("No studies found", className="alert-heading mb-2"),
                html.P(message, className="mb-0"),
            ],
            color="light",
            className="mb-0 text-center py-5",
        )

    table = dbc.Table(
        [
            html.Thead(html.Tr([
                html.Th("Study name"),
                html.Th("Tumor type"),
                html.Th("Data"),
                html.Th("Total patients"),
                html.Th("Actions", className="text-end"),
            ])),
            html.Tbody(_build_study_rows(records)),
        ],
        bordered=False,
        hover=True,
        responsive=True,
        className="align-middle mb-0 bg-white",
    )

    if len(records) > 10:
        return html.Div(
            table,
            style={
                "maxHeight": "520px",
                "overflowY": "auto",
                "overflowX": "auto",
                "border": "1px solid #e2e8f0",
                "borderRadius": "0.75rem",
            },
        )

    return table


def filter_and_sort_studies(records, query="", tumor_filter="all", sort_by="study_name", sort_desc=False):
    filtered = records[:]
    q = (query or "").strip().lower()
    tumor_filter = (tumor_filter or "all").strip().lower()

    if q:
        filtered = [r for r in filtered if q in r["study_name"].lower()]
    if tumor_filter != "all":
        filtered = [r for r in filtered if str(r["tumor_type"]).lower() == tumor_filter]

    def sort_key(record):
        if sort_by == "tumor_type":
            return str(record["tumor_type"]).lower()
        if sort_by == "created_at":
            return _parse_created_at(str(record["created_at"]))
        if sort_by == "total_pzt":
            try:
                return int(record["total_pzt"])
            except Exception:
                return -1
        return str(record["study_name"]).lower()

    filtered.sort(key=sort_key, reverse=bool(sort_desc))
    return filtered


def serve_studies_layout(output_root=DEFAULT_OUTPUT_ROOT, query="", tumor_filter="all", sort_by="study_name", sort_desc=False):
    records = get_study_records(output_root)
    filtered_records = filter_and_sort_studies(records, query=query, tumor_filter=tumor_filter, sort_by=sort_by, sort_desc=sort_desc)
    tumor_types = sorted({r["tumor_type"] for r in records if r.get("tumor_type") and r["tumor_type"] != "Unknown"})
    tumor_options = [{"label": "All tumor types", "value": "all"}] + [
        {"label": tumor, "value": tumor.lower()} for tumor in tumor_types
    ]

    return dbc.Container([
        dcc.Download(id="study-download-wrapper"),
        html.Div([
            html.H2("Saved Studies", className="mt-4 fw-bold"),
            html.P("Open a previous run or remove it from the results folder.", className="text-muted"),
            dbc.Card(
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.Label("Study name"),
                            dbc.Input(
                                id="study_name_filter",
                                type="text",
                                placeholder="Filter by study name...",
                                value=query,
                            ),
                        ], md=4),
                        dbc.Col([
                            html.Label("Tumor type"),
                            dbc.Select(
                                id="tumor_type_filter",
                                options=tumor_options,
                                value=tumor_filter,
                            ),
                        ], md=3),
                        dbc.Col([
                            html.Label("Sort by"),
                            dbc.Select(
                                id="study_sort_by",
                                options=[
                                    {"label": "Study name", "value": "study_name"},
                                    {"label": "Tumor type", "value": "tumor_type"},
                                    {"label": "Date", "value": "created_at"},
                                    {"label": "Total patients", "value": "total_pzt"},
                                ],
                                value=sort_by,
                            ),
                        ], md=3),
                        dbc.Col([
                            html.Label("Descending"),
                            dbc.Checklist(
                                id="study_sort_desc",
                                options=[{"label": "Reverse order", "value": 1}],
                                value=[1] if sort_desc else [],
                                switch=True,
                            ),
                        ], md=2, className="pt-2"),
                    ], className="g-3 align-items-end"),
                    html.Div(
                        f"Showing {len(filtered_records)} of {len(records)} studies",
                        id="studies-summary",
                        className="text-muted small mt-3",
                    ),
                ]),
                className="mt-3 shadow-sm border-0"
            ),
            dbc.Card(
                dbc.CardBody([
                    html.Div(
                        render_studies_table(filtered_records),
                        id="studies-table-container"
                    )
                ]),
                className="mt-3 shadow-sm border-0"
            ),
        ]),
    ], fluid=True, className="py-4", style={"maxWidth": "1000px"})
