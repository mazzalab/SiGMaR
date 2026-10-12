from dash import html, dcc
import dash_bootstrap_components as dbc
from config import get_button_style


def serve_layout_clinical_association():
    return dbc.Container([
        html.Div(style={"height": "1.25rem"}),
        html.H2("Clinical Association", className="mt-2 fw-bold"),
        html.Hr(),

        dbc.Card([
            dbc.CardHeader(html.H5("1. Reference Study", className="mb-0")),
            dbc.CardBody([
                html.P(
                    "Select the study from Results to use as the reference for the clinical association analysis.",
                    className="text-muted small",
                ),
                dcc.Dropdown(
                    id="ca_study_select",
                    options=[],
                    value=None,
                    clearable=False,
                    placeholder="Select a study from Results",
                ),
                html.Div(id="ca_selected_study_label", className="mt-3 fw-semibold"),
                html.Hr(className="my-3"),
                html.Label("Upload new clinical file", className="mb-1 small text-muted"),
                dcc.Upload(
                    id="ca_annotation_upload",
                    children=html.Div([
                        html.Span("Drag and drop or "),
                        html.A("select a clinical file"),
                    ]),
                    multiple=False,
                    accept=".csv,.tsv,.txt,.xlsx",
                    style={
                        "width": "100%",
                        "minHeight": "74px",
                        "borderWidth": "1px",
                        "borderStyle": "dashed",
                        "borderRadius": "8px",
                        "borderColor": "#99f6e4",
                        "display": "flex",
                        "alignItems": "center",
                        "justifyContent": "center",
                        "backgroundColor": "#f8fafc",
                        "cursor": "pointer",
                    },
                ),
                html.Div(id="ca_annotation_upload_status", className="mt-2"),
                html.Label("Sample ID column", className="mt-3 mb-1 small text-muted"),
                dcc.Dropdown(
                    id="ca_sample_column_select",
                    options=[],
                    value=None,
                    placeholder="Select the sample ID column",
                    clearable=False,
                    disabled=True,
                ),
                html.Div(id="ca_sample_match_status", className="mt-2"),
            ])
        ], className="mb-4 shadow-sm border-0"),

        dbc.Card([
            dbc.CardHeader(html.H5("2. Clinical Variables", className="mb-0")),
            dbc.CardBody([
                html.Div(id="ca_clinical_missing_banner"),
                html.Label("Select one or more clinical variables", className="mb-1 small text-muted"),
                dcc.Dropdown(
                    id="ca_clinical_vars_select",
                    options=[],
                    value=[],
                    multi=True,
                    placeholder="Clinical variables will appear here",
                    disabled=True,
                ),
                dbc.Row([
                    dbc.Col([
                        html.Label("Agreement threshold (%)", className="mt-3 mb-1 small text-muted"),
                        dbc.Input(
                            id="ca_agreement_threshold",
                            type="number",
                            min=0,
                            max=100,
                            step=1,
                            value=70,
                            disabled=False,
                            style={"width": "110px"},
                        ),
                    ], width="auto"),
                    dbc.Col([
                        html.Label(" ", className="mt-3 mb-1 small text-muted d-block"),
                        dbc.Checklist(
                            id="ca_use_all_samples",
                            options=[{"label": "Use all samples", "value": "all"}],
                            value=[],
                            className="pt-1",
                            switch=True,
                        ),
                    ], width="auto"),
                ], className="align-items-end g-3"),
                html.Label("Axis orientation", className="mt-3 mb-1 small text-muted"),
                dcc.RadioItems(
                    id="ca_axis_orientation",
                    options=[
                        {"label": "Subtype on X-axis", "value": "subtype_x"},
                        {"label": "Clinical variable on X-axis", "value": "clinical_x"},
                    ],
                    value="subtype_x",
                    inline=True,
                ),
                dbc.Row([
                    dbc.Col(
                        dbc.Button(
                            "Run Clinical Association",
                            id="ca_run_btn",
                            className="shadow-sm",
                            style=get_button_style("jade"),
                            disabled=True,
                        ),
                        width="auto",
                    ),
                    dbc.Col(
                        dbc.Button(
                            "Go to Results",
                            id={"type": "nav_btn", "index": "ca_results_btn"},
                            className="shadow-sm fw-bold",
                            style=get_button_style("mist"),
                            disabled=True,
                        ),
                        width="auto",
                        className="ms-auto",
                    ),
                ], className="mt-4 align-items-center"),
            ])
        ], className="shadow-sm border-0"),

        dcc.Download(id="ca-download-wrapper"),
        dcc.Store(id="ca-rendered-run-images-store"),
        dcc.Store(id="ca_annotation_upload_signal"),
        dcc.Loading(
            html.Div(id="ca_results_container", className="mt-4"),
            id="loading-clinical-association",
            type="circle",
        ),
    ], fluid=True, className="py-5", style={
        "maxWidth": "1100px",
        "paddingTop": "1rem",
        "paddingBottom": "2rem",
    })
