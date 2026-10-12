import os
import zipfile

import dash
from dash import Input, Output, State, ALL, dcc

from config import DEFAULT_OUTPUT_ROOT
from layouts.layout_studies import get_study_records, filter_and_sort_studies, render_studies_table


def _cache_dir(study_path):
    cache_dir = os.path.join(study_path, ".sigmar_cache")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def _latest_tree_mtime(root_dir, skip_names=None):
    skip_names = set(skip_names or [])
    latest = 0.0
    for root, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in skip_names]
        for file_name in files:
            if file_name in skip_names:
                continue
            path = os.path.join(root, file_name)
            try:
                latest = max(latest, os.path.getmtime(path))
            except OSError:
                continue
    return latest


def _cache_is_fresh(cache_path, source_mtime):
    if not os.path.exists(cache_path):
        return False
    try:
        return os.path.getmtime(cache_path) >= float(source_mtime or 0)
    except OSError:
        return False


def register_callbacks_studies(app):
    @app.callback(
        Output("studies-table-container", "children"),
        Output("studies-summary", "children"),
        Input("study_name_filter", "value"),
        Input("tumor_type_filter", "value"),
        Input("study_sort_by", "value"),
        Input("study_sort_desc", "value"),
    )
    def update_studies_table(query, tumor_filter, sort_by, sort_desc):
        # Always the project's own results folder, regardless of any custom
        # output_root picked on the Upload page for a specific run - Results
        # should be one predictable place to find every study, not follow
        # whatever folder happens to be persisted in the current session.
        records = get_study_records(DEFAULT_OUTPUT_ROOT)
        filtered_records = filter_and_sort_studies(
            records,
            query=query or "",
            tumor_filter=tumor_filter or "all",
            sort_by=sort_by or "study_name",
            sort_desc=bool(sort_desc),
        )
        empty_message = "No studies match your current filter." if records else "No saved studies found in uploads/results."
        table = render_studies_table(filtered_records, empty_message=empty_message)
        summary = f"Showing {len(filtered_records)} of {len(records)} studies"
        return table, summary

    @app.callback(
        Output("study-download-wrapper", "data"),
        Input({"type": "study_download_btn", "study": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def download_study_folder(n_clicks):
        from dash import ctx

        if not n_clicks or not any((isinstance(click, (int, float)) and click > 0) for click in n_clicks):
            return dash.no_update

        trig_id = ctx.triggered_id
        if not isinstance(trig_id, dict) or trig_id.get("type") != "study_download_btn":
            return dash.no_update

        study_name = trig_id.get("study")
        if not study_name:
            return dash.no_update

        # Matches update_studies_table(): Results always lists studies from
        # DEFAULT_OUTPUT_ROOT, so Download must look there too, not in
        # whatever output_root a session happens to have persisted.
        study_path = os.path.join(DEFAULT_OUTPUT_ROOT, study_name)
        if not os.path.isdir(study_path):
            return dash.no_update

        archive_name = f"{study_name}.zip"
        cache_dir = _cache_dir(study_path)
        cache_path = os.path.join(cache_dir, archive_name)
        source_mtime = _latest_tree_mtime(study_path, skip_names={".sigmar_cache"})
        if _cache_is_fresh(cache_path, source_mtime):
            return dcc.send_file(cache_path)

        with zipfile.ZipFile(cache_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(study_path):
                dirs[:] = [d for d in dirs if d != ".sigmar_cache"]
                for file_name in files:
                    if file_name == ".sigmar_cache":
                        continue
                    file_path = os.path.join(root, file_name)
                    arcname = os.path.relpath(file_path, study_path)
                    zf.write(file_path, arcname)

        return dcc.send_file(cache_path)
