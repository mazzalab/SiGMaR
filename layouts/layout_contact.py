from urllib.parse import quote

from dash import html
import dash_bootstrap_components as dbc

FEEDBACK_EMAIL = "sigmar.tool_help@yahoo.com"


def _section(title, body, background, accent):
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


def _build_bug_report_mailto():
    subject = "SiGMaR Bug Report"
    body = (
        "Run name: \n"
        "Tumor type: \n"
        "Description of the issue: \n\n"
        "(If relevant, attach the run's log - see <output folder>/logs/ or run_report.txt in the study folder)"
    )
    return f"mailto:{FEEDBACK_EMAIL}?subject={quote(subject)}&body={quote(body)}"


def serve_layout_contact():
    help_and_contacts = (
        "Need help? Check Documentation for input formats, methods and a step-by-step "
        "guide, or About for details on the project and team. Can't find what you're "
        "looking for? Use the form below to get in touch."
    )

    feedback_body = html.Div(
        [
            html.P(
                "Found a bug, or something isn't working as expected? Send us an email - "
                "please include your run name, the tumor type and, where relevant, the run's "
                "log so the issue can be reproduced.",
                className="mb-3",
                style={"color": "#0f172a"},
            ),
            dbc.Button(
                "Report a bug / Contact us",
                href=_build_bug_report_mailto(),
                external_link=True,
                target="_blank",
                className="fw-bold shadow-sm",
                style={
                    "backgroundColor": "#0F766E",
                    "border": "none",
                    "borderRadius": "999px",
                    "padding": "10px 22px",
                },
            ),
        ]
    )

    return dbc.Container(
        [
            html.H2("Contact", className="mt-4 fw-bold mb-4"),
            _section(
                "Help & Contacts",
                help_and_contacts,
                "linear-gradient(135deg, #FFF1F2 0%, #FFE4E6 100%)",
                "#EA580C",
            ),
            _section(
                "Feedback & Bug Reports",
                feedback_body,
                "linear-gradient(135deg, #ECFEFF 0%, #CCFBF1 100%)",
                "#0F766E",
            ),
        ],
        fluid=True,
        className="py-4",
        style={"maxWidth": "1000px"},
    )
