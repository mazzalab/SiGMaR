# callbacks/callbacks_upload.py
import json
import os
import shutil
import dash
import pandas as pd
from dash import Input, Output, State, callback_context, html, dash_table
import dash_bootstrap_components as dbc
from scripts.function import read_table_preview, read_table_headers
from config import UPLOAD_FOLDER_TEMP, DEFAULT_OUTPUT_ROOT, is_sigmar_study_dir, get_display_output_root, join_display_path


def _normalize_name(value):
    return str(value).strip().lower()


def _resolve_output_root(value):
    """Always DEFAULT_OUTPUT_ROOT - `value` is kept as a parameter only so
    callers reading output_root_input's (fixed, disabled) value don't need
    special-casing. See layout_upload.py's Output Location card for why a
    custom root is no longer offered: it made a study invisible to
    Results/Saved Studies, which only ever scans DEFAULT_OUTPUT_ROOT."""
    return DEFAULT_OUTPUT_ROOT


def _build_dropdown_options(columns):
    return [{"label": str(col), "value": str(col)} for col in columns]


def _detect_gene_column(columns):
    if not columns:
        return None
    exact_matches = {
        "gene", "genes", "gene_id", "geneid", "gene name", "genename", "symbol", "hugo_symbol"
    }
    for col in columns:
        normalized = _normalize_name(col)
        if normalized in exact_matches:
            return str(col)
    for col in columns:
        normalized = _normalize_name(col)
        if "gene" in normalized:
            return str(col)
    return str(columns[0])


def _detect_sample_column(columns):
    if not columns:
        return None
    exact_matches = {
        "sample", "samples", "sample_id", "sampleid", "sample id", "sample name", "sample_name", "id"
    }
    for col in columns:
        normalized = _normalize_name(col)
        if normalized in exact_matches:
            return str(col)
    for col in columns:
        normalized = _normalize_name(col)
        if "sample" in normalized:
            return str(col)
    return str(columns[0])


def _standardize_table(path, selected_column, detector):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return None
    df = read_table_preview(path, nrows=None)
    columns = [str(c) for c in df.columns]
    if not columns:
        return None
    chosen = selected_column if selected_column in columns else detector(columns)
    if chosen not in columns:
        return None
    ordered_columns = [chosen] + [c for c in columns if c != chosen]
    df = df.loc[:, ordered_columns]
    df.to_csv(path, index=False)
    return chosen


def _find_uploaded_source_file(folder_path, standardized_name):
    if not os.path.isdir(folder_path):
        return None
    standardized_path = os.path.join(folder_path, standardized_name)
    if os.path.exists(standardized_path):
        return standardized_path
    candidates = []
    for entry in os.listdir(folder_path):
        full_path = os.path.join(folder_path, entry)
        if not os.path.isfile(full_path):
            continue
        if entry == standardized_name:
            continue
        candidates.append(full_path)
    candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return candidates[0] if candidates else None


def _materialize_standard_csv(source_path, target_path):
    if not source_path or not os.path.exists(source_path):
        return False
    if os.path.abspath(source_path) == os.path.abspath(target_path):
        return True
    df = read_table_preview(source_path, nrows=None)
    df.to_csv(target_path, index=False)
    try:
        os.remove(source_path)
    except OSError:
        pass
    return True


def _copy_input_to_output(source_path, output_dir, filename):
    if not source_path or not output_dir or not os.path.exists(source_path):
        return False
    os.makedirs(output_dir, exist_ok=True)
    target_path = os.path.join(output_dir, filename)
    if os.path.abspath(source_path) == os.path.abspath(target_path):
        return True
    shutil.copy2(source_path, target_path)
    return True


def _write_input_metadata(output_dir, counts_gene_column=None, clinical_sample_column=None):
    if not output_dir:
        return
    os.makedirs(output_dir, exist_ok=True)
    metadata_path = os.path.join(output_dir, "input_metadata.json")
    metadata = {}
    if os.path.exists(metadata_path):
        try:
            with open(metadata_path, "r") as f:
                metadata = json.load(f) or {}
        except Exception:
            metadata = {}
    if counts_gene_column is not None:
        metadata["counts_gene_column"] = counts_gene_column
    if clinical_sample_column is not None:
        metadata["clinical_sample_column"] = clinical_sample_column
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)


def create_file_tab(label, df):
    """Crea una tab con l'anteprima della tabella."""
    return dbc.Tab(label=f"{label} ({df.shape[0]}x{df.shape[1]})", children=[
        dash_table.DataTable(
            data=df.to_dict("records"),
            columns=[{"name": c, "id": c} for c in df.columns],
            page_size=10, 
            style_table={'overflowX': 'auto'},
            style_cell={'textAlign': 'left', 'padding': '5px'},
            style_header={'backgroundColor': 'rgb(230, 230, 230)', 'fontWeight': 'bold'}
        )
    ])

def register_callbacks_upload(app):

    # 1. Sincronizzazione degli Input nella memoria persistente (Store)
    @app.callback(
        [Output("collapse_tumor_section", "is_open"),
         Output("collapse_upload_section", "is_open")],
        [Input("output_location_confirmed", "data"),
         Input("tumor_type_select", "value")]
    )
    def toggle_sections(location_confirmed, tumor_type):
        step2_open = bool(location_confirmed)
        step3_open = bool(step2_open and tumor_type)
        return step2_open, step3_open

    @app.callback(
        [Output("folder_name_persistent", "data"),
         Output("tumor_type_persistent", "data"),
         Output("base_path_persistent", "data")],
        [Input("folder_name_input", "value"),
         Input("tumor_type_select", "value"),
         Input("output_root_input", "value")]
    )

    def sync_to_storage(folder, tumor, output_root):
        return folder, tumor, _resolve_output_root(output_root)

    # 1b. Output location confirmation - this is the one place the run
    # folder actually gets created on disk (and the only place the
    # "already has data" / "can't save here" checks run). Editing the root
    # or the run folder name after confirming invalidates it again, so
    # sections 2/3 (gated on output_location_confirmed, see toggle_sections)
    # lock back up until the user re-confirms the new location.
    @app.callback(
        [Output("output_location_confirmed", "data"),
         Output("path_status_feedback", "children"),
         Output("confirm_output_location_btn", "children")],
        [Input("confirm_output_location_btn", "n_clicks"),
         Input("output_root_input", "value"),
         Input("folder_name_input", "value")],
        prevent_initial_call=False,
    )
    def confirm_output_location(n_clicks, output_root_raw, folder_name):
        output_root = _resolve_output_root(output_root_raw)
        resolved_folder = folder_name.strip() if folder_name else ""
        resolved_path = os.path.join(output_root, resolved_folder) if resolved_folder else output_root
        # "Saving to:" shows the real local path (see get_display_output_root()),
        # not resolved_path (the container-internal /app/... one actually used
        # for all the disk I/O below).
        display_path = join_display_path(get_display_output_root(), resolved_folder)
        saving_line = html.Span(f"Saving to: {display_path}", className="text-info")

        triggered_id = callback_context.triggered_id
        if triggered_id != "confirm_output_location_btn":
            # Root/folder name changed (or first render) - nothing confirmed
            # yet for *this* path, just show the live preview.
            return False, saving_line, "Confirm Output Location"

        if len(resolved_folder) < 3:
            notice = dbc.Alert(
                "Run folder name must be at least 3 characters before confirming.",
                color="danger", className="mt-2 mb-0 py-2",
            )
            return False, html.Div([saving_line, notice]), "Confirm Output Location"

        already_has_data = os.path.isdir(resolved_path) and is_sigmar_study_dir(resolved_path)
        try:
            _write_input_metadata(resolved_path)
        except (OSError, NotADirectoryError) as exc:
            notice = dbc.Alert(
                f"Can't save to \"{resolved_path}\": {exc.strerror or exc}. "
                "Pick a different output folder or run folder name.",
                color="danger", className="mt-2 mb-0 py-2",
            )
            return False, html.Div([saving_line, notice]), "Confirm Output Location"

        if already_has_data:
            notice = dbc.Alert(
                "⚠️ This folder already has data - it will be overwritten.",
                color="warning", className="mt-2 mb-0 py-2",
            )
            return True, html.Div([saving_line, notice]), "✓ Location Confirmed"

        return True, saving_line, "✓ Location Confirmed"

    # (The folder-browser modal that used to let a user pick a custom output
    # root - navigate/create-folder/select callbacks - was removed together
    # with its layout in layout_upload.py: a study saved outside
    # DEFAULT_OUTPUT_ROOT was invisible to Results/Saved Studies, so the
    # output root is fixed now instead of worked around.)

    # 3. Gestione Upload, Anteprime e Validazione Tasto Next
    # NOTE: the output folder itself is created/validated once, up front, by
    # confirm_output_location() - this callback only writes into it (the
    # chosen gene/sample columns) once output_location_confirmed is True;
    # it no longer touches path_status_feedback (section 1's job now).
    @app.callback(
        [Output("preview_container", "children"),
         Output({"type": "nav_btn", "index": "next_btn"}, "disabled"),
         Output("counts_validation_feedback", "children"),
         Output("counts_gene_column_select", "options"),
         Output("counts_gene_column_select", "value"),
         Output("clinical_sample_column_select", "options"),
         Output("clinical_sample_column_select", "value"),
         Output("counts_gene_column_persistent", "data"),
         Output("clinical_sample_column_persistent", "data")],
        [Input("url", "pathname"),
         Input("counts_uploader", "isCompleted"),
         Input("annotation_uploader", "isCompleted"),
         #Input("token_uploader", "isCompleted"),
         Input("folder_name_input", "value"),
         Input("tumor_type_select", "value"),
         Input("remove_counts_btn", "n_clicks"),
         Input("remove_annot_btn", "n_clicks"),
         Input("counts_gene_column_select", "value"),
         Input("clinical_sample_column_select", "value"),
         Input("output_root_input", "value"),
         Input("output_location_confirmed", "data"),
         #Input("remove_token_btn", "n_clicks")
         ],
        prevent_initial_call=False
    )
    def handle_uploads_and_validation(pathname, c_done, a_done, folder_name, tumor_type, rem_c, rem_a, gene_choice, sample_choice, output_root, location_confirmed):
        if pathname != "/upload":
            return (dash.no_update,) * 9

        output_root = _resolve_output_root(output_root)

        ctx = callback_context
        triggered_props = [item["prop_id"].split(".")[0] for item in ctx.triggered] if ctx.triggered else []
        trigger = triggered_props[0] if triggered_props else "url"

        counts_folder = os.path.join(UPLOAD_FOLDER_TEMP, "counts")
        annotation_folder = os.path.join(UPLOAD_FOLDER_TEMP, "annotation")
        c_path = os.path.join(counts_folder, "counts.csv")
        a_path = os.path.join(annotation_folder, "annotation.csv")
        #t_path = "uploads/temp/token/token.csv"

        if "remove_counts_btn" in triggered_props:
            shutil.rmtree(counts_folder, ignore_errors=True)
            os.makedirs(counts_folder, exist_ok=True)
            return (
                html.Div(),
                True,
                html.Div(),
                [],
                None,
                [],
                None,
                None,
                None,
            )

        if "remove_annot_btn" in triggered_props:
            shutil.rmtree(annotation_folder, ignore_errors=True)
            os.makedirs(annotation_folder, exist_ok=True)

        upload_errors = []
        counts_source_path = _find_uploaded_source_file(counts_folder, "counts.csv")
        annotation_source_path = _find_uploaded_source_file(annotation_folder, "annotation.csv")

        # Gestione rimozione file
        if "remove_counts" in trigger:
            counts_source_path = None
        if "remove_annot" in trigger:
            annotation_source_path = None
        # if "remove_token" in trigger:
        #     shutil.rmtree("uploads/temp/token", ignore_errors=True)
        #     os.makedirs("uploads/temp/token", exist_ok=True)

        counts_options = []
        counts_value = None
        clinical_options = []
        clinical_value = None
        preview_cards = []

        if counts_source_path:
            try:
                counts_columns = read_table_headers(counts_source_path)
                counts_options = _build_dropdown_options(counts_columns)
                counts_value = gene_choice if gene_choice in counts_columns else _detect_gene_column(counts_columns)
                preview_cards.append(
                    dbc.Card(
                        dbc.CardBody([
                            html.H6("Counts file", className="mb-1"),
                            html.Div(os.path.basename(counts_source_path), className="small text-muted"),
                            html.Div(f"{len(counts_columns)} columns found", className="small"),
                        ]),
                        className="shadow-sm border-0",
                    )
                )
            except Exception as exc:
                upload_errors.append(
                    dbc.Alert(
                        f"Error reading counts file: {exc}",
                        color="danger",
                        className="mb-3",
                    )
                )

        if annotation_source_path:
            try:
                clinical_columns = read_table_headers(annotation_source_path)
                clinical_options = _build_dropdown_options(clinical_columns)
                clinical_value = sample_choice if sample_choice in clinical_columns else _detect_sample_column(clinical_columns)
                preview_cards.append(
                    dbc.Card(
                        dbc.CardBody([
                            html.H6("Clinical file", className="mb-1"),
                            html.Div(os.path.basename(annotation_source_path), className="small text-muted"),
                            html.Div(f"{len(clinical_columns)} columns found", className="small"),
                        ]),
                        className="shadow-sm border-0",
                    )
                )
            except Exception:
                pass

        # Validazione per abilitare il tasto "Next" - la location deve
        # essere stata confermata (Card 1) prima di poter proseguire.
        counts_exists = counts_source_path is not None and counts_value is not None
        folder_filled = folder_name is not None and len(folder_name.strip()) > 0
        tumor_selected = tumor_type is not None and tumor_type != ""

        resolved_folder = folder_name.strip() if folder_name else ""

        if location_confirmed and folder_filled and resolved_folder:
            output_dir = os.path.join(output_root, resolved_folder)
            try:
                _write_input_metadata(
                    output_dir,
                    counts_gene_column=counts_value,
                    clinical_sample_column=clinical_value,
                )
            except (OSError, NotADirectoryError):
                # Already surfaced to the user by confirm_output_location();
                # nothing new to show here.
                pass

        is_ready = bool(location_confirmed) and counts_exists and folder_filled and tumor_selected
        next_disabled = not is_ready

        content = dbc.Row(
            [dbc.Col(card, width=6) for card in preview_cards],
            className="g-3",
        ) if preview_cards else html.Div()
        validation_feedback = html.Div(upload_errors)

        return (
            content,
            next_disabled,
            validation_feedback,
            counts_options,
            counts_value,
            clinical_options,
            clinical_value,
            counts_value,
            clinical_value,
        )
