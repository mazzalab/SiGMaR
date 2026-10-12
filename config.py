import os
import re
from dash import html
import dash_bootstrap_components as dbc

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))

CALLBACK_DIR = os.path.join(PROJECT_ROOT, "callbacks")
LAYOUTS_DIR = os.path.join(PROJECT_ROOT, "layouts")
SCRIPT_DIR = os.path.join(PROJECT_ROOT, "scripts")
UPLOAD_FOLDER = os.path.join(PROJECT_ROOT, "uploads")
UPLOAD_FOLDER_STUDIES = os.path.join(UPLOAD_FOLDER, "studies")
UPLOAD_FOLDER_TEMP = os.path.join(UPLOAD_FOLDER, "temp")
UPLOAD_FOLDER_RESULTS = os.path.join(UPLOAD_FOLDER, "results")
DEFAULT_OUTPUT_ROOT = UPLOAD_FOLDER_RESULTS


def get_display_output_root():
    """DEFAULT_OUTPUT_ROOT, for display only, as the real path the user
    would actually find it at on their machine.

    On macOS/Linux DEFAULT_OUTPUT_ROOT already *is* that path - the
    container's working dir is bind-mounted at the same path it has on the
    host there (docker-compose.yaml's `${HOME}:${HOME}` /
    `working_dir: ${PWD}`), so PROJECT_ROOT (derived from __file__) already
    resolves to the real host directory.

    On Windows it's /app - a container-internal path with no meaning to the
    user - so this reconstructs the real one from HOST_MOUNT_ROOT (see
    docker-compose.win.yaml), which holds it in POSIX drive-letter form
    (/c/Users/x/SiGMaR); converted here to the native Windows form
    (C:\\Users\\x\\SiGMaR) since that's what the user would actually type
    into Explorer. Falls back to DEFAULT_OUTPUT_ROOT unchanged if
    HOST_MOUNT_ROOT isn't set (e.g. an older installer, or run outside
    Docker) rather than showing something wrong.
    """
    host_root = os.environ.get("HOST_MOUNT_ROOT", "")
    match = re.match(r"^/([A-Za-z])/(.*)$", host_root)
    if not match:
        return DEFAULT_OUTPUT_ROOT
    drive, rest = match.groups()
    native_root = f"{drive.upper()}:\\" + rest.replace("/", "\\")
    return native_root + "\\uploads\\results"


def join_display_path(display_root, *parts):
    """Appends `parts` to a get_display_output_root() value for showing a
    specific run's path in the UI (e.g. the "Saving to: ..." line) - using
    backslash if display_root looks like a native Windows path (it has none
    of its own, being a drive-letter root), os.path.join otherwise."""
    parts = [p for p in parts if p]
    if not parts:
        return display_root
    if "\\" in display_root or re.match(r"^[A-Za-z]:$", display_root):
        return display_root + "\\" + "\\".join(parts)
    return os.path.join(display_root, *parts)


# Files/subfolders that mark a directory as an actual SiGMaR study output
# (written during upload/analysis - see callbacks_upload.py/annotator.R).
# Used to filter what counts as a "study" wherever a folder is scanned
# (Saved Studies list, the "folder already has data" upload warning).
SIGMAR_STUDY_MARKERS = (
    "input_metadata.json", "counts.csv", "annotation.csv",
    "report_metadata.json", "dashboard_data.json",
    "NTP", "ssGSEA", "TMP", "Centroid_Correlation", "breast_subtype",
)


def is_sigmar_study_dir(path):
    """True if `path` looks like a real SiGMaR study output, not just any
    directory that happens to live under the configured output root."""
    return any(os.path.exists(os.path.join(path, marker)) for marker in SIGMAR_STUDY_MARKERS)

TUMOR_TYPE_LABELS = {
    "bladder": {"label": "Bladder Cancer (BLCA)", "short": "BLCA"},
    "blca": {"label": "Bladder Cancer (BLCA)", "short": "BLCA"},
    "brca_pam50": {"label": "Breast Cancer (BRCA)", "short": "BRCA"},
    "brca": {"label": "Breast Cancer (BRCA)", "short": "BRCA"},
    "coad": {"label": "Colon Adenocarcinoma (COAD)", "short": "COAD"},
    "gbm": {"label": "Glioblastoma (GBM)", "short": "GBM"},
    "hnscc": {"label": "Head and Neck Squamous Cell Carcinoma (HNSCC)", "short": "HNSCC"},
    "luad": {"label": "Lung Adenocarcinoma (LUAD)", "short": "LUAD"},
    "lusc": {"label": "Lung Squamous Cell Carcinoma (LUSC)", "short": "LUSC"},
    "meso": {"label": "Mesothelioma (MESO)", "short": "MESO"},
    "ov": {"label": "Ovarian Cancer (OV)", "short": "OV"},
    "pdac": {"label": "Pancreatic Adenocarcinoma (PDAC)", "short": "PDAC"},
    "sarc": {"label": "Sarcoma (SARC)", "short": "SARC"},
}


def format_tumor_type(value, mode="short"):
    if value is None:
        return "Unknown"

    raw = str(value).strip()
    if not raw:
        return "Unknown"

    key = raw.lower()
    entry = TUMOR_TYPE_LABELS.get(key)
    if entry:
        return entry.get(mode, entry["short"])

    return raw.upper()


TUMOR_TYPE_PILL_STYLES = {
    "blca": {"backgroundColor": "#0F766E", "color": "#ffffff", "border": "1px solid rgba(255,255,255,0.18)"},
    "brca": {"backgroundColor": "#F59E0B", "color": "#ffffff", "border": "1px solid rgba(255,255,255,0.18)"},
    "coad": {"backgroundColor": "#0EA5A4", "color": "#ffffff", "border": "1px solid rgba(255,255,255,0.18)"},
    "gbm": {"backgroundColor": "#EA580C", "color": "#ffffff", "border": "1px solid rgba(255,255,255,0.18)"},
    "hnscc": {"backgroundColor": "#14B8A6", "color": "#ffffff", "border": "1px solid rgba(255,255,255,0.18)"},
    "luad": {"backgroundColor": "#22C55E", "color": "#ffffff", "border": "1px solid rgba(255,255,255,0.18)"},
    "lusc": {"backgroundColor": "#2563EB", "color": "#ffffff", "border": "1px solid rgba(255,255,255,0.18)"},
    "meso": {"backgroundColor": "#D97706", "color": "#ffffff", "border": "1px solid rgba(255,255,255,0.18)"},
    "ov": {"backgroundColor": "#8B5CF6", "color": "#ffffff", "border": "1px solid rgba(255,255,255,0.18)"},
    "pdac": {"backgroundColor": "#F43F5E", "color": "#ffffff", "border": "1px solid rgba(255,255,255,0.18)"},
    "sarc": {"backgroundColor": "#059669", "color": "#ffffff", "border": "1px solid rgba(255,255,255,0.18)"},
}

TUMOR_TYPE_PILL_BASE_STYLE = {
    "display": "inline-flex",
    "alignItems": "center",
    "justifyContent": "center",
    "minWidth": "108px",
    "height": "30px",
    "padding": "0 14px",
    "borderRadius": "999px",
    "fontSize": "12px",
    "fontWeight": "700",
    "letterSpacing": "0",
    "lineHeight": "1",
    "whiteSpace": "nowrap",
    "textAlign": "center",
    "boxSizing": "border-box",
}

BUTTON_PALETTE = {
    "jade": {
        "backgroundColor": "#0F766E",
        "borderColor": "#0F766E",
        "color": "#ffffff",
    },
    "sunrise": {
        "backgroundColor": "#F59E0B",
        "borderColor": "#F59E0B",
        "color": "#ffffff",
    },
    "seafoam": {
        "backgroundColor": "#14B8A6",
        "borderColor": "#14B8A6",
        "color": "#ffffff",
    },
    "coral": {
        "backgroundColor": "#F97316",
        "borderColor": "#F97316",
        "color": "#ffffff",
    },
    "mist": {
        "backgroundColor": "#ECFEFF",
        "borderColor": "#99F6E4",
        "color": "#0F766E",
    },
}


def get_button_style(name):
    return BUTTON_PALETTE.get(name, BUTTON_PALETTE["jade"]).copy()


def get_logo_src(filename):
    return f"/logo/{filename}"


def get_tumor_type_pill_style(value):
    raw = format_tumor_type(value, mode="short")
    style = TUMOR_TYPE_PILL_STYLES.get(str(raw).lower(), {
        "backgroundColor": "#64748b",
        "color": "#ffffff",
        "border": "1px solid rgba(255,255,255,0.18)"
    })
    return {**TUMOR_TYPE_PILL_BASE_STYLE, **style}


def style_dict_to_css(style_dict):
    parts = []
    for key, value in style_dict.items():
        css_key = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", key).lower()
        parts.append(f"{css_key}: {value}")
    return "; ".join(parts)


def create_nav_bar():
    return dbc.Navbar(
        dbc.Container([
            html.A(
                html.Div(
                    [
                        html.Img(
                            src=get_logo_src("sigmar_logo.png"),
                            alt="SiGMaR",
                            style={
                                "height": "50px",
                                "width": "auto",
                                "display": "block",
                            },
                        ),
                        html.Span(
                            "SiGMar",
                            style={
                                "marginLeft": "10px",
                                "fontSize": "1.35rem",
                                "fontWeight": "700",
                                "color": "#0f172a",
                                "letterSpacing": "0.01em",
                                "lineHeight": "1",
                            },
                        ),
                    ],
                    style={
                        "display": "flex",
                        "alignItems": "center",
                    },
                ),
                href="/",
                className="navbar-brand d-flex align-items-center p-0 m-0",
                style={"lineHeight": "1"},
            ),
            dbc.Nav(
                [
                    dbc.NavItem(dbc.NavLink("Home", href="/", id={"type": "nav_btn", "index": "home_btn"}, active="exact", className="px-3 nav-link-tropical", n_clicks=0)),
                    dbc.NavItem(dbc.NavLink("Subtyping", href="/upload", id={"type": "nav_btn", "index": "new_analysis_btn"}, active="exact", className="px-3 nav-link-tropical", n_clicks=0)),
                    dbc.NavItem(dbc.NavLink("Clinical Association", href="/clinical-association", id={"type": "nav_btn", "index": "clinical_association_btn"}, active="exact", className="px-3 nav-link-tropical", n_clicks=0)),
                    dbc.NavItem(dbc.NavLink("Results", href="/results", id={"type": "nav_btn", "index": "results_btn"}, active="partial", className="px-3 nav-link-tropical", n_clicks=0)),
                    dbc.NavItem(dbc.NavLink("About", href="/about", id={"type": "nav_btn", "index": "about_btn"}, active="exact", className="px-3 nav-link-tropical", n_clicks=0)),
                    dbc.NavItem(dbc.NavLink("Documentation", href="/documentation", id={"type": "nav_btn", "index": "documentation_btn"}, active="exact", className="px-3 nav-link-tropical", n_clicks=0)),
                    dbc.NavItem(dbc.NavLink("Contact", href="/contact", id={"type": "nav_btn", "index": "contact_btn"}, active="exact", className="px-3 nav-link-tropical", n_clicks=0)),
                    dbc.NavItem(
                        html.A(
                            "Stop",
                            href="/shutdown",
                            target="_self",
                            className="ms-2 px-3 fw-bold nav-stop-link",
                            style={
                                "display": "inline-flex",
                                "alignItems": "center",
                                "justifyContent": "center",
                                "height": "32px",
                                "marginTop": "3px",
                                "borderRadius": "999px",
                                "backgroundColor": "#dc2626",
                                "border": "1px solid #dc2626",
                                "color": "#ffffff",
                                "textDecoration": "none",
                                "lineHeight": "1",
                                "boxShadow": "0 4px 12px rgba(220, 38, 38, 0.24)",
                            },
                        )
                    ),
                ],
                className="ms-auto",
                navbar=True,
            ),
        ], fluid=True, className="py-0"),
        color="#ffffff",
        dark=False,
        className="shadow-sm border-bottom py-1 bg-white",
        fixed="top",
        style={
            "paddingTop": "0.25rem",
            "paddingBottom": "0.25rem",
            "boxShadow": "0 8px 24px rgba(15, 23, 42, 0.08)",
        },
    )


def create_footer_bar():
    return html.Footer(
        dbc.Container(
            [
                html.Div(
                    [
                        html.Img(
                            src=get_logo_src("mazzalab_logo.jpeg"),
                            alt="Mazza Lab",
                            style={
                                "height": "42px",
                                "width": "auto",
                                "display": "block",
                            },
                        ),
                        html.Div(
                            [
                                html.Div("Gemelli Computational Biology"),
                                html.Div("and Bioinformatics Lab"),
                            ],
                            style={
                                "marginLeft": "12px",
                                "fontSize": "13px",
                                "fontWeight": "700",
                                "lineHeight": "1.18",
                                "color": "#0f172a",
                                "letterSpacing": "0",
                                "whiteSpace": "nowrap",
                            },
                        ),
                    ],
                    className="d-flex align-items-center",
                ),
                html.Div(style={"flex": "1 1 auto"}),
                # GSTEP footer logo removed temporarily.
                # html.A(
                #     html.Img(
                #         src=get_logo_src("GSTEP_logo.png"),
                #         alt="GSTEP",
                #         style={
                #             "height": "42px",
                #             "width": "auto",
                #             "display": "block",
                #             "cursor": "pointer",
                #         },
                #     ),
                #     href="https://gstep.policlinicogemelli.it",
                #     target="_blank",
                #     rel="noopener noreferrer",
                # ),
            ],
            fluid=True,
            className="d-flex align-items-center justify-content-between py-3",
        ),
        style={
            "borderTop": "1px solid #e2e8f0",
            "backgroundColor": "#ffffff",
            "boxShadow": "0 -6px 24px rgba(15, 23, 42, 0.04)",
            "position": "fixed",
            "left": "0",
            "right": "0",
            "bottom": "0",
            "zIndex": "1030",
        },
    )
