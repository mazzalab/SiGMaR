from dash import html
import dash_bootstrap_components as dbc
from config import get_logo_src


def _quick_link_item(label, nav_index, accent):
    # A real <a href> here would navigate via a full page reload, which
    # callbacks_navigation.py's route_from_path() bounces back to Home
    # whenever nav_source_persistent isn't yet "app" (its default before any
    # in-app nav_btn click this session - e.g. right on first load). A
    # link-styled Button has no href to navigate with, so only the nav_btn
    # n_clicks callback path fires - the same one the rest of the app's
    # navigation already relies on, which sets nav_source to "app" itself.
    return html.Li(
        dbc.Button(
            label,
            id={"type": "nav_btn", "index": nav_index},
            n_clicks=0,
            color="link",
            className="fw-semibold p-0 align-baseline",
            style={"color": accent, "textDecoration": "underline", "fontSize": "1rem"},
        ),
        className="mb-1",
    )


def serve_home_layout():
    what_is_sigmar = (
        "SiGMaR is a local, containerized application for molecular subtyping of bulk RNA-seq data across 11 tumor types. "
        "It runs multiple independent classifiers, including Nearest Template Prediction, single-sample GSEA, centroid-based methods, tumor-specific tools, and GDAN-TMP models,"
        "and combines their predictions into a consensus subtype call with an agreement score."
    )

    return dbc.Container(
        [
            html.Div(
                [
                    html.Img(
                        src=get_logo_src("sigmar_logo.png"),
                        alt="SiGMaR",
                        className="img-fluid",
                        style={
                            "maxWidth": "260px",
                            "width": "min(60vw, 260px)",
                            "height": "auto",
                            "display": "block",
                            "margin": "0 auto",
                            "filter": "drop-shadow(0 18px 30px rgba(15, 23, 42, 0.12))",
                        },
                    ),
                    html.H3(
                        "Welcome to SiGMaR!",
                        className="mt-4 mb-0 fw-semibold text-center",
                        style={"letterSpacing": "0.02em", "color": "#0f172a"},
                    ),
                ],
                className="text-center py-4",
            ),
            dbc.Card(
                dbc.CardBody(
                    [
                        html.H3("What is SiGMaR?", className="fw-bold mb-3", style={"color": "#0F766E"}),
                        html.P(what_is_sigmar, className="lh-lg", style={"color": "#0f172a"}),
                        html.Ul(
                            [
                                # Distinct ids from the persistent top-nav's new_analysis_btn/
                                # about_btn/documentation_btn/contact_btn (config.py's
                                # create_nav_bar) - that navbar renders on every page including
                                # this one, so reusing those same {"type":"nav_btn",...} ids here
                                # would be a duplicate-id collision. Routed to the same pages via
                                # their own branches in callbacks_navigation.py's nav_btn handler.
                                _quick_link_item("Launch your analysis", "home_upload_link", "#0F766E"),
                                _quick_link_item("For more info", "home_documentation_link", "#F59E0B"),
                                _quick_link_item("About Us", "home_about_link", "#EA580C"),
                                _quick_link_item("Contact Us", "home_contact_link", "#0F766E"),
                            ],
                            className="mb-0 ps-3",
                        ),
                    ]
                ),
                className="shadow-sm border-0 mb-4",
                style={
                    "borderRadius": "1.25rem",
                    "background": "linear-gradient(135deg, #ECFEFF 0%, #CCFBF1 100%)",
                },
            ),
        ],
        fluid=True,
        className="py-5",
        style={"maxWidth": "1100px"},
    )
