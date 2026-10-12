from dash import html, dcc
import dash_bootstrap_components as dbc
from config import get_button_style

def status_row(label, method_id):
    """
    Funzione helper per creare le righe dei metodi.
    Include il nome del metodo e i tre stati (spinner, check, croce).
    """
    return dbc.Row([
        dbc.Col(html.P(label, className="mb-0", style={"fontSize": "15px", "fontWeight": "500"}), width=8),
        dbc.Col([
            # 1. Rotella (Spinner)
            dbc.Spinner(size="sm", color="primary", id=f"spin-{method_id}", spinner_style={"display": "none"}),
            # 2. Spunta Verde (Successo)
            html.Span("✅", id=f"check-{method_id}", style={"display": "none", "fontSize": "18px"}),
            # 3. Croce Rossa (Errore)
            html.Span("❌", id=f"err-{method_id}", style={"display": "none", "fontSize": "18px"}),
            # 4. Scritta Skipped (Grigetto e corsivo)
            html.Small("Skipped", id=f"skip-{method_id}",
                       style={"display": "none", "color": "#6c757d", "fontStyle": "italic"})
        ], width=4, className="text-end")
    ], className="py-2 border-bottom align-items-center")

# Tumors whose two subtype systems differ: the GDAN-TMP models are optional there.
DIVIDED_TUMORS = {"coad", "coadread", "read", "gbm", "hnsc", "hnscc", "luad", "lusc", "meso", "pdac", "paad"}
# Tumors with a validated weighting (see utilities/consensus_scheme.tsv).
WEIGHTING_TUMORS = {"luad", "lusc", "pdac", "paad", "brca", "brca_pam50", "breast"}


def _toggle_style(tumor_type, allowed):
    """Show a toggle only where it does something. Decided while the page is built, so the
    section never depends on a callback firing after the layout is swapped in."""
    return {"display": "block"} if str(tumor_type or "").strip().lower() in allowed else {"display": "none"}


def serve_layout_analysis(tumor_type=None):
    return dbc.Container([
        # --- COMPONENTI TECNICI (Invisibili) ---
        dcc.Store(id='analysis-step-tracker', data=0),
        # Intervallo che controlla il polling dei processi R
        dcc.Interval(id='progress-interval', interval=1500, n_intervals=0, disabled=True),

        html.Div(style={"height": "1.25rem"}),
        html.H2("Analysis - Subtyping", className="mt-2 fw-bold"),
        html.Hr(),
        
        # --- CARD 1: NORMALIZZAZIONE (Sincrona) ---
        dbc.Card([
            dbc.CardHeader(html.H5("1. DESeq2 Normalization", className="mb-0")),
            dbc.CardBody([
                html.P(["Normalize raw counts and optionally apply Batch Correction.",
                       html.Br(),
                       html.Span(
                           "Perform this step only if you are working with a raw count matrix.",
                           style={"color": "red"})
            ], className="text-muted small"),
                dbc.Checklist(
                    options=[{"label": "Enable Batch Correction", "value": 1, "disabled": False}],
                    value=[],
                    id="batch_correction_tick",
                    switch=True,
                ),
                dbc.Collapse(
                    dbc.Card(
                        dbc.CardBody([
                            html.Label("Batch column", className="mb-1 small text-muted"),
                            dcc.Dropdown(
                                id="batch_column_select",
                                options=[],
                                value=None,
                                clearable=False,
                                placeholder="Select the batch column",
                            ),
                        ]),
                        className="border-0 shadow-sm mt-3",
                    ),
                    id="batch_column_collapse",
                    is_open=False,
                ),
                dbc.Button("Run Normalization", id="normalize_btn", className="mt-3 shadow-sm", style=get_button_style("jade")),

                dcc.Loading(
                    id="loading-normalization",
                    type="circle",
                    children=html.Div(id="normalize_output", className="mt-2")
                )
            ])
        ], className="mb-4 shadow-sm border-0"),

        # --- CARD 2: PREDICTION (Asincrona con Rotelle) ---
        dbc.Card([
            dbc.CardHeader(html.H5("2. Prediction Pipeline", className="mb-0")),
            dbc.CardBody([
                html.P("Run the consensus subtyping methods on the normalized data.", className="text-muted small"),
                html.Div(
                    [
                        html.P("GDAN-TMP is an alternative subtyping method that can give different results than the standard classification. " \
                        "Check the box to also run it.", className="text-muted small"),
                        dbc.Checklist(
                            options=[{"label": "Run GDAN-TMP models", "value": 1}],
                            value=[],
                            id="run_tmp_tick",
                            switch=True,
                            className="mb-2",
                        ),
                    ],
                    # Hidden for tumors outside the "divided" list, where TMP
                    # always runs regardless of this toggle (see monitor_steps'
                    # divided_tumors check) - showing a checkbox with no effect
                    # there would be misleading.
                    id="tmp_toggle_section",
                    style=_toggle_style(tumor_type, DIVIDED_TUMORS),
                ),
                html.Div(
                    [
                        html.P("Weight each method's vote by its validated accuracy for this tumor type, "
                               "instead of counting all methods equally.", className="text-muted small"),
                        dbc.Checklist(
                            options=[{"label": "Apply validated method weighting", "value": 1}],
                            value=[],
                            id="weighting_tick",
                            switch=True,
                            className="mb-3",
                        ),
                    ],
                    # Hidden for tumors outside WEIGHTING_TUMORS, where the
                    # validated weighting scheme isn't available and equal
                    # vote always applies - showing a permanently disabled
                    # checkbox there was more confusing than informative.
                    id="weighting_toggle_section",
                    style=_toggle_style(tumor_type, WEIGHTING_TUMORS),
                ),
                dbc.Row([
                    dbc.Col([
                        dbc.Button("Run Subtyping",
                                   id="btn-run-annotation", 
                                   className="shadow-sm", 
                                   disabled=False,
                                   style=get_button_style("sunrise")),
                    ], width="auto"),
                    dbc.Col([
                        # Badge di stato generale (es. "Analysis Completed!")
                        html.Div(id='ntp-status-badge', className="mt-1")
                    ], width="auto"),
                    dbc.Col([
                        dbc.Button(
                            "🔍 View Error Details",
                            id="view_error_details_btn",
                            size="sm",
                            color="danger",
                            outline=True,
                            style={"display": "none"},
                        ),
                    ], width="auto"),

                    # --- NUOVO: BOTTONE VAI AI RISULTATI ---
                    dbc.Col([
                        dbc.Button(
                            "Go to Results", 
                            id={"type": "nav_btn", "index": "analysis_results_btn"}, # INDICE IMPORTANTE
                            disabled=True,
                            className="shadow-sm fw-bold",
                            style=get_button_style("mist")
                        )
                    ], width="auto", className="ms-auto") # Spinto a destra
                ], className="mb-4 align-items-center"),

                dcc.Store(id="last_step_error"),
                dbc.Modal([
                    dbc.ModalHeader(dbc.ModalTitle(id="error_details_modal_title")),
                    dbc.ModalBody(
                        html.Pre(
                            id="error_details_modal_body",
                            className="small",
                            style={"whiteSpace": "pre-wrap", "wordBreak": "break-word", "maxHeight": "60vh", "overflowY": "auto"},
                        ),
                    ),
                    dbc.ModalFooter(
                        html.Small(id="error_details_modal_path", className="text-muted"),
                    ),
                ], id="error_details_modal", is_open=False, size="lg", scrollable=True),

                # LISTA DEI METODI AGGIORNATA
                html.Div([
                    status_row("Preparing Data", "prepare"),
                    status_row("Nearest Template Prediction (NTP)", "ntp"),
                    status_row("Single Sample GSEA (ssGSEA)", "ssgsea"),
                    status_row("Centroid Correlation", "centroid"),
                    status_row("Tumor Molecular Pathology (TMP)", "tmp"),
                    status_row("Consensus Ovary", "cons_ov"),
                    status_row("CMS", "cms"),
                    status_row("Breast Subtype", "breast_subtype"),
                    
                    # --- NUOVA RIGA PER IL MERGE FINALE ---
                    status_row("Finalizing & Reporting", "finalize"),
                ], className="px-2", style={"backgroundColor": "#f8f9fa", "borderRadius": "8px"}),
                
            ])
        ], className="mb-4 shadow-sm border-0"),

        # TASTO BACK
        dbc.Row([
        dbc.Col(dbc.Button("← Back to Upload", id={"type": "nav_btn", "index": "back_to_upload_btn"}, style=get_button_style("mist")), width="auto"),
        ], className="mb-5"),

    ], fluid=True, className="py-5", style={
        "maxWidth": "1000px",
        "paddingTop": "1rem",
        "paddingBottom": "2rem",
    })
