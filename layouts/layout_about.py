from dash import html
import dash_bootstrap_components as dbc


def _section(title, text, background, accent):
    return dbc.Card(
        dbc.CardBody(
            [
                html.H3(title, className="fw-bold mb-3", style={"color": accent}),
                html.P(text, className="mb-0 lh-lg", style={"color": "#0f172a"}),
            ]
        ),
        className="shadow-sm border-0 mb-4",
        style={
            "borderRadius": "1.25rem",
            "background": background,
        },
    )


# One name per person; add/remove people or categories freely -
# _people_section() below renders however many there are.
PEOPLE = {
    "Project Lead": [
        "Tommaso Mazza, PhD",
    ],
    "Scientific Coordination": [
        "Giulia Mantini, PhD",
    ],
    "Design and Development Team": [
        "Chiara Parrillo, MSc",
        "Mina Karimi, MSc",
        "Anna Provvidenza Privitera, PhD",
    ],
}


def _people_column(category, names):
    return dbc.Col(
        [
            html.Div(
                html.Span(
                    category,
                    className="fw-bold",
                    style={"color": "#0F766E", "fontSize": "1.05rem"},
                ),
                className="mb-3",
            ),
            html.Div(
                [html.Div(name, className="mb-2", style={"color": "#334155"}) for name in names]
            ),
        ],
        md=4,
        className="mb-4",
    )


def _people_section():
    return dbc.Card(
        dbc.CardBody(
            [
                html.H3("People", className="fw-bold mb-3", style={"color": "#0F766E"}),
                dbc.Row(
                    [_people_column(category, names) for category, names in PEOPLE.items()],
                    className="g-4",
                ),
            ]
        ),
        className="shadow-sm border-0 mb-4",
        style={
            "borderRadius": "1.25rem",
            "background": "linear-gradient(135deg, #ECFEFF 0%, #CCFBF1 100%)",
        },
    )


# TODO: replace with the real citation (paper/preprint reference, DOI, or a
# BibTeX block) once available.
HOW_TO_CITE = (
    "If you use SiGMaR in your research, please cite: "
    "[Author list]. SiGMaR: [paper title]. [Journal/preprint], [year]. "
    "DOI: [xx.xxxx/xxxxx]."
)


def serve_layout_about():
    return dbc.Container(
        [
            html.H2("About", className="mt-4 fw-bold mb-4"),
            _people_section(),
            _section(
                "How to cite us",
                HOW_TO_CITE,
                "linear-gradient(135deg, #FFF7ED 0%, #FEF3C7 100%)",
                "#F59E0B",
            ),
        ],
        fluid=True,
        className="py-4",
        style={"maxWidth": "1000px"},
    )
