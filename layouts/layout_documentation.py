from dash import html
import dash_bootstrap_components as dbc

def _section(title, body, background, accent):
    # body can be a plain string (rendered as a paragraph, as before) or a
    # Dash component/list of components for sections that need real
    # structure (e.g. an ordered list) instead of one dense paragraph.
    content = (
        html.P(body, className="mb-0 lh-lg", style={"color": "#0f172a"})
        if isinstance(body, str)
        else body
    )
    return dbc.Card(
        dbc.CardBody(
            [
                html.H3(title, className="fw-bold mb-3", style={"color": accent}),
                content,
            ]
        ),
        className="shadow-sm border-0 mb-4",
        style={
            "borderRadius": "1.25rem",
            "background": background,
        },
    )

def _step_list(steps, note=None, ordered=True):
    # ordered=True renders a numbered <ol> for a sequence that must be
    # followed in order (e.g. the run workflow); ordered=False renders a
    # plain bulleted <ul> for parallel/independent items (e.g. file types)
    # where numbering would wrongly imply a required order.
    items = [
        html.Li(
            [
                html.Span(label, className="fw-semibold", style={"color": "#0f172a"}),
                html.Span(f" — {detail}", style={"color": "#334155"}),
            ],
            className="mb-2",
        )
        for label, detail in steps
    ]
    list_tag = html.Ol if ordered else html.Ul
    children = [list_tag(items, className="ps-3 mb-3", style={"lineHeight": "1.7"})]
    if note:
        children.append(
            html.P(note, className="mb-0 fst-italic", style={"color": "#475569"})
        )
    return html.Div(children)

def _subsection(title, body, className="mb-4"):
    return html.Div(
        [
            html.H5(title, className="fw-bold mb-2", style={"color": "#0f172a"}),
            body,
        ],
        className=className,
    )

def serve_layout_documentation():
    subtyping_steps = _step_list(
        [
            (
                "Start a run",
                "Open Subtyping, give the run a name, and click 'Confirm Output Location' to confirm the folder choice.",
            ),
            (
                "Pick the tumor type",
                "This determines which centroids, tumor-specific tools and TMP models are used.",
            ),
            (
                "Upload your data",
                "Upload a counts file (required) and a clinical file (optional). "
                "For the counts file specify the gene column; for clinical files specify the sample column. "
                "Click 'Next -> Subtyping' bottom to continue.",
            ),
            (
                "Normalize",
                "Normalize raw counts with DESeq2. "
                "This step should only be performed if the input matrix contains raw counts. "
                "If a clinical file is provided, you can also select a clinical variable/column to account for potential confounding effects during normalization.",
            ),
            (
                "Subtype",
                "Run Subtyping to execute all methods in sequence. "
                "For some tumor types (COAD, GBM, HNSC, LUAD, LUSC, MESO, PDAC), GDAN-TMP models are optional and are not included in the report by default due to a mismatch with the TCGA-based classification. "
                "Check the box to compute them as a secondary classification.",
            ),
            (
                "Check the results",
                "Open Results to view the consensus call and per-method predictions.",
            ),
        ],
        note="Every run is saved and can be reopened from Results at any time.",
    )
    clinical_association_steps = _step_list(
        [
            (
                "Pick the reference study",
                "On the Clinical Association page, select a completed Subtyping run from "
                "Results to use as the reference.",
            ),
            (
                "Add clinical data",
                "Upload a clinical file (or reuse the one already attached to the run) and "
                "confirm the sample ID column.",
            ),
            (
                "Choose variables",
                "Select one or more clinical variables to test against the predicted subtypes.",
            ),
            (
                "Set the sample filter",
                "Optionally set an agreement-score threshold (default 70%) to exclude "
                "low-confidence samples, or tick \"Use all samples\".",
            ),
            (
                "Run and review",
                "Click Run Clinical Association, then check the statistics and plots below "
                "or open Results.",
            ),
        ],
    )
    manage_studies_steps = _step_list(
        [
            (
                "Open a study",
                "On Results, click 'Open' on a saved study to reopen its report "
                "(Subtyping and Clinical Association tabs).",
            ),
            (
                "Download outputs",
                "Click 'Download' to get a .zip with everything in that study's output "
                "folder (predictions, reports, plots).",
            ),
            (
                "Delete a study",
                "Click 'Delete' to permanently remove the study folder from disk. "
                "This cannot be undone.",
            ),
        ],
        ordered=False,
    )
    stop_app = _step_list(
        [
            (
                "Stop the app",
                "Click the 'Stop' button to close the application.",
            ),
        ],
    )

    def _group_heading(title):
        return html.H4(title, className="fw-bold mb-3 mt-4", style={"color": "#0f172a"})

    user_guide = html.Div(
        [
            _group_heading("Create New Study"),
            _subsection("Subtyping", subtyping_steps),
            _subsection("Clinical Association", clinical_association_steps, className=""),

            _group_heading("Manage Studies"),
            manage_studies_steps,

            _group_heading("Stop Application"),
            stop_app,
        ]
    )
    input_files = _step_list(
        [
            (
                "Counts file (required)",
                "CSV, TSV, TXT or XLSX with one column of gene identifiers and one numeric "
                "column per sample. SiGMaR tries to detect the gene column automatically; "
                "you can correct it before running.",
            ),
            (
                "Clinical file (optional)",
                "Needed for Clinical Association: a sample-ID column plus one or more "
                "clinical or biological variables.",
            ),
        ],
        note="Sample IDs in the counts and clinical files must match.",
        ordered=False,
    )
    outputs = html.Div(
        [
            html.P(
                "Every run opens as a report with three tabs:",
                className="mb-2",
                style={"color": "#334155"},
            ),
            _step_list(
                [
                    (
                        "Table",
                        "Per-sample predictions from each classification method, the final "
                        "consensus subtype and an agreement score reflecting how strongly "
                        "the methods concur.",
                    ),
                    (
                        "Graphics",
                        "Subtype View (distribution of samples across the predicted "
                        "subtypes) and Sample View (per-method predictions for each sample, "
                        "color-coded by subtype so disagreement between methods stands out).",
                    ),
                    (
                        "Clinical Associations",
                        "Tests whether the predicted subtypes relate to clinical variables, "
                        "once a clinical file has been provided.",
                    ),
                ],
                ordered=False,
            ),
            _subsection(
                "Downloads",
                html.P(
                    "The whole report can be exported as CSV, PDF, HTML or a full ZIP "
                    "folder. Each chart can also be downloaded on its own as PNG, TIFF or "
                    "PDF, at 150 or 300 dpi.",
                    className="mb-0",
                    style={"color": "#334155"},
                ),
                className="mt-3",
            ),
        ]
    )
    models_used = _step_list(
        [
            (
                "Nearest Template Prediction (NTP)",
                "Cosine-similarity matching against the most specific marker genes for "
                "each subtype, derived from the reference centroids.",
            ),
            (
                "Single-sample GSEA (ssGSEA)",
                "Per-sample enrichment scores for gene sets built by thresholding the "
                "reference centroids into up/down-regulated markers per subtype.",
            ),
            (
                "Centroid Correlation",
                "Pearson, Cosine and Euclidean similarity between each sample's "
                "expression profile and the reference centroids.",
            ),
            (
                "GDAN-TMP",
                "Ensemble of five independently-trained classifiers (AKLIMATE, "
                "CloudForest, JADBio, SK-Grid, SubSCOPE) from the TCGA GDAN Tumor "
                "Molecular Pathology project. Optional for tumor types whose TMP "
                "classification doesn't align with the TCGA-based one (see User Guide).",
            ),
            (
                "Consensus OV",
                "Ovarian cancer only - wraps the consensusOV Bioconductor package.",
            ),
            (
                "CMS",
                "Colorectal cancer only - Consensus Molecular Subtypes classification.",
            ),
            (
                "Breast Subtype (PAM50)",
                "Breast cancer only - intrinsic subtyping (Basal, Her2, LumA, LumB, Normal).",
            ),
        ],
        ordered=False,
    )

    return dbc.Container(
        [
            html.H2("Documentation", className="mt-4 fw-bold mb-4"),
            _section(
                "Input Files",
                input_files,
                "linear-gradient(135deg, #FFF7ED 0%, #FEF3C7 100%)",
                "#F59E0B",
            ),
            _section(
                "User Guide",
                user_guide,
                "linear-gradient(135deg, #ECFEFF 0%, #CCFBF1 100%)",
                "#0F766E",
            ),
            _section(
                "Results & Outputs",
                outputs,
                "linear-gradient(135deg, #F0FDF4 0%, #DCFCE7 100%)",
                "#0F766E",
            ),
            _section(
                "Models Used",
                models_used,
                "linear-gradient(135deg, #FFF7ED 0%, #FEF3C7 100%)",
                "#F59E0B",
            ),
        ],
        fluid=True,
        className="py-4",
        style={"maxWidth": "1000px"},
    )
