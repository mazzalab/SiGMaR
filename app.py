import dash
import dash_bootstrap_components as dbc
import dash_uploader as du
from dash import html, dcc
import os
import shutil
import subprocess
import threading
import time
from flask import abort, send_file

from callbacks.callbacks_upload import register_callbacks_upload
from callbacks.callbacks_analysis import register_callbacks_analysis
from callbacks.callbacks_navigation import register_navigation_callback
from callbacks.callbacks_studies import register_callbacks_studies
from callbacks.callbacks_results import register_callbacks_results
from callbacks.callbacks_clinical_association import register_callbacks_clinical_association
from layouts.layout_home import serve_home_layout
from config import UPLOAD_FOLDER_TEMP, UPLOAD_FOLDER_RESULTS, DEFAULT_OUTPUT_ROOT, create_nav_bar, create_footer_bar, PROJECT_ROOT


app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.FLATLY],
    #external_scripts=external_scripts,
    suppress_callback_exceptions=True
)
app.title = "SiGMar"
app.index_string = """
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <style>
            .nav-link-tropical {
                color: #0f172a !important;
                font-weight: 600;
                border-radius: 999px;
                transition: background-color 0.18s ease, color 0.18s ease;
            }
            .nav-link-tropical:hover {
                color: #0f766e !important;
                background: rgba(15, 118, 110, 0.08);
            }
            .nav-link-tropical.active {
                color: #0f766e !important;
                background: rgba(15, 118, 110, 0.12);
            }
            .nav-stop-link:hover {
                background: #b91c1c !important;
                border-color: #b91c1c !important;
                color: #ffffff !important;
            }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
"""


@app.server.route("/logo/<path:filename>")
def serve_logo(filename):
    logo_dir = os.path.join(PROJECT_ROOT, "logo")
    file_path = os.path.join(logo_dir, filename)
    if not os.path.isfile(file_path):
        abort(404)

    lower_name = filename.lower()
    mimetype = "image/png"
    if lower_name.endswith((".jpg", ".jpeg")):
        mimetype = "image/jpeg"
    elif lower_name.endswith(".svg"):
        mimetype = "image/svg+xml"
    elif lower_name.endswith(".ai"):
        mimetype = "application/pdf"

    return send_file(file_path, mimetype=mimetype)


def _run_shutdown_command():
    time.sleep(1)
    env = os.environ.copy()
    env["PWD"] = PROJECT_ROOT
    env["HOST_PWD"] = PROJECT_ROOT

    compose_file = os.path.join(PROJECT_ROOT, "docker-compose.yaml")
    if shutil.which("docker") and os.path.exists(compose_file):
        compose_candidates = [
            ["docker", "compose", "-f", compose_file, "down"],
            ["docker-compose", "-f", compose_file, "down"],
        ]
        for command in compose_candidates:
            try:
                subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=True)
                return
            except FileNotFoundError:
                continue
            except subprocess.CalledProcessError:
                continue

        # Minimal fallback for images that have the Docker CLI but not Compose.
        subprocess.run(["docker", "rm", "-f", "sigmar_container"], check=False)
        subprocess.run(["docker", "network", "rm", "sigmar_default"], check=False)


@app.server.route("/shutdown")
def shutdown_app():
    threading.Thread(target=_run_shutdown_command, daemon=True).start()
    return """
<!DOCTYPE html>
<html>
  <head>
    <title>SiGMar stopping</title>
    <style>
      body {
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        background: #f8fafc;
        color: #0f172a;
      }
      main {
        width: min(520px, calc(100vw - 32px));
        padding: 28px;
        border: 1px solid #fecaca;
        border-radius: 8px;
        background: #ffffff;
        box-shadow: 0 16px 40px rgba(15, 23, 42, 0.12);
      }
      h1 {
        margin: 0 0 10px;
        font-size: 24px;
      }
      p {
        margin: 0;
        line-height: 1.5;
        color: #475569;
      }
    </style>
  </head>
  <body>
    <main>
      <h1>SiGMar is stopping</h1>
      <p>The Docker containers are being shut down. You can close this browser tab in a few seconds.</p>
    </main>
  </body>
</html>
"""

# Configurazione cartelle
os.makedirs(UPLOAD_FOLDER_RESULTS, exist_ok=True)
os.makedirs(UPLOAD_FOLDER_TEMP, exist_ok=True)
du.configure_upload(app, UPLOAD_FOLDER_TEMP)

app.layout = html.Div([
    dcc.Location(id="url", pathname="/", refresh=False),

    # MEMORIA PERSISTENTE: Questi ID non vengono mai distrutti al cambio pagina
    dcc.Store(id="tumor_type_persistent", storage_type='session'),
    dcc.Store(id="base_path_persistent", storage_type='session', data=DEFAULT_OUTPUT_ROOT),
    dcc.Store(id="folder_name_persistent", storage_type='session'),
    dcc.Store(id="counts_gene_column_persistent", storage_type='session'),
    dcc.Store(id="clinical_sample_column_persistent", storage_type='session'),
    dcc.Store(id="batch_column_persistent", storage_type='session'),
    dcc.Store(id="selected_study_persistent", storage_type='session'),
    dcc.Store(id="nav_source_persistent", storage_type='session'),

    create_nav_bar(),
    html.Main(
        dbc.Container(
            id="page-content",
            children=serve_home_layout(),
            fluid=True,
            className="pt-4",
            style={
                "maxWidth": "100%",
                "paddingTop": "13.5rem",
                "paddingBottom": "8rem",
                "minHeight": "100%",
            },
        ),
        style={
            "flex": "1 1 auto",
            "overflowY": "auto",
            "overflowX": "hidden",
        },
    ),
    create_footer_bar(),
], style={
    "height": "100vh",
    "display": "flex",
    "flexDirection": "column",
    "backgroundColor": "#f8fafc",
    "overflow": "hidden",
})

# Registrazione logiche
register_callbacks_upload(app)
register_callbacks_analysis(app)
register_navigation_callback(app)
register_callbacks_studies(app)
register_callbacks_results(app)
register_callbacks_clinical_association(app)

if __name__ == "__main__":
    print("\n" + "="*50)
    print("  SigMar Dashboard is ready!")
    print("  Access it here: http://localhost:8060/")
    print("="*50 + "\n")
    app.run(debug=True, port=8060, host='0.0.0.0')
