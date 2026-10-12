import dash_uploader as du
import dash_bootstrap_components as dbc
from dash import html, dcc
from config import get_button_style, get_display_output_root

def serve_layout_upload(tumor_type=None, base_path=None, folder_name=None, counts_gene_column=None, clinical_sample_column=None):
    return dbc.Container([
        html.Div(style={"height": "1.25rem"}),
        html.H2("Analysis - Upload Files", className="mt-2"),
        html.Hr(),

        dbc.Card([
            dbc.CardHeader(html.H5("1. Output Location", className="mb-0 fw-bold")),
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Label("Output root directory"),
                        # Fixed to DEFAULT_OUTPUT_ROOT - no longer user-editable.
                        # A custom output folder used to be possible here (via a
                        # folder-browser picker), but a study saved outside this
                        # default root never showed up in Results/Saved Studies
                        # (that page only ever scans DEFAULT_OUTPUT_ROOT, see
                        # callbacks_studies.py) - reachable only right after
                        # finishing that one analysis, in that same browser
                        # session. Removed rather than worked around: every
                        # study now always lives in the one place Results
                        # actually looks.
                        dbc.Input(
                            id="output_root_input",
                            # Shown as the real local path (e.g.
                            # C:\Users\x\...\uploads\results), not the
                            # container-internal DEFAULT_OUTPUT_ROOT
                            # (/app/uploads/results) - see
                            # get_display_output_root(). Purely cosmetic:
                            # every downstream callback still resolves the
                            # actual save location to DEFAULT_OUTPUT_ROOT
                            # regardless of this field's value.
                            value=get_display_output_root(),
                            type="text",
                            disabled=True,
                        ),
                        html.Div(id="path_status_feedback", className="mt-2 small"),
                    ], width=7),
                    dbc.Col([
                        html.Label("Run folder name"),
                        dbc.Input(
                            id="folder_name_input",
                            placeholder="Es: run_01",
                            type="text",
                            value=folder_name if folder_name else "",
                            debounce=True,
                        ),
                    ], width=5),
                ]),
                dbc.Row(
                    dbc.Col(
                        dbc.Button(
                            "Confirm Output Location",
                            id="confirm_output_location_btn",
                            style=get_button_style("jade"),
                        ),
                        width=12, className="text-end",
                    ),
                    className="mt-3",
                ),
            ])
        ], color="light", className="mb-4"),

        # True only right after a successful Confirm click, for the exact
        # folder_name it was confirmed with - editing it after confirming
        # invalidates it again (see confirm_output_location()), so sections
        # 2/3 stay locked until the user re-confirms the new location.
        dcc.Store(id="output_location_confirmed", data=False),

        dbc.Collapse(
            dbc.Card([
                dbc.CardHeader(html.H5("2. Biological Context", className="mb-0 fw-bold")),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.Label("Select Tumor Type:"),
                            dbc.Select(
                                id="tumor_type_select",
                                options=[
                                    {"label": "Bladder Cancer (BLCA)", "value": "bladder"},
                                    {"label": "Breast Cancer (BRCA)", "value": "brca_pam50"},
                                    {"label": "Colon Adenocarcinoma (COAD)", "value": "coad"},
                                    {"label": "Glioblastoma (GBM)", "value": "gbm"},
                                    {"label": "Head and Neck Squamous Cell Carcinoma (HNSCC)", "value": "hnscc"},
                                    {"label": "Lung Adenocarcinoma (LUAD)", "value": "luad"},
                                    {"label": "Lung Squamous Cell Carcinoma (LUSC)", "value": "lusc"},
                                    {"label": "Mesothelioma (MESO)", "value": "meso"},
                                    {"label": "Ovarian Cancer (OV)", "value": "ov"},
                                    {"label": "Pancreatic Adenocarcinoma (PDAC)", "value": "pdac"},
                                    {"label": "Sarcoma (SARC)", "value": "sarc"},
                                ],
                                value=tumor_type,
                                placeholder="Select a tumor type...",
                            ),
                        ], width=12),
                    ])
                ])
            ], color="light", className="mb-4"),
            id="collapse_tumor_section",
            is_open=False
        ),

        dbc.Collapse(
            dbc.Card([
                dbc.CardHeader(html.H5("3. Load Data", className="mb-0 fw-bold")),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.H6("Counts file (Required)"),
                            du.Upload(
                                id="counts_uploader",
                                upload_id="counts",
                                filetypes=["csv", "tsv", "txt", "xlsx"],
                            ),
                            html.Label("Gene column", className="mt-2 mb-1 small text-muted"),
                            dcc.Dropdown(
                                id="counts_gene_column_select",
                                options=[],
                                value=counts_gene_column,
                                placeholder="Select the gene column",
                                clearable=False,
                            ),
                            dbc.Button("Remove Counts", id="remove_counts_btn", color="danger", size="sm", className="mt-2", outline=True)
                        ], width=6),
                        dbc.Col([
                            html.H6("Clinical file (Optional)"),
                            du.Upload(
                                id="annotation_uploader",
                                upload_id="annotation",
                                filetypes=["csv", "tsv", "txt", "xlsx"],
                            ),
                            html.Label("Sample ID column", className="mt-2 mb-1 small text-muted"),
                            dcc.Dropdown(
                                id="clinical_sample_column_select",
                                options=[],
                                value=clinical_sample_column,
                                placeholder="Select the sample ID column",
                                clearable=False,
                            ),
                            dbc.Button("Remove Annotation", id="remove_annot_btn", color="danger", size="sm", className="mt-2", outline=True)
                        ], width=6),
                        # dbc.Col([
                        #     html.H6("Synapse Token (Optional)"),
                        #     du.Upload(id="token_uploader", upload_id="token"),
                        #     dbc.Button("Remove Token", id="remove_token_btn", 
                        #                color="danger", size="sm", className="mt-2", outline=True),
                        #     html.Div(
                        #         html.Small("Required for TMP subtyping.", className="text-muted d-block mt-1"),
                        #     )
                        # ], width=6),
                    ]),
                    html.Div(id="counts_validation_feedback", className="mt-3"),
                ])
            ], color="light", className="mb-4"),
            id="collapse_upload_section",
            is_open=False
        ),
        
        html.Div(id="preview_container", className="mt-4"),
        html.Hr(),
        dbc.Row([
            dbc.Col(
                dbc.Button(
                    "Next → Subtyping",
                    id={"type": "nav_btn", "index": "next_btn"},
                    size="lg",
                    disabled=True,
                    style=get_button_style("mist"),
                ),
                width="auto",
            ),
        ], justify="end", className="mb-5"),
        
    ], fluid=True, style={"paddingTop": "1rem"})
