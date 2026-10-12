import os
import zipfile
from io import BytesIO
from pathlib import Path
import base64
import json
import re

import dash
from dash import Input, Output, State, dcc
import dash_bootstrap_components as dbc
from PIL import Image

from callbacks.callbacks_analysis import get_clean_path
from layouts.layout_results import build_html_report, build_pdf_report_bytes, build_graphic_export_bytes, _build_results_table, _load_clinical_association_summary, _clinical_association_card
from scripts.clinical_association import build_clinical_association_export_bytes

HTML_CACHE_VERSION = "v6_20261008_statserror"
PDF_CACHE_VERSION = "v6_20260519_manualpdf"


def _decode_data_url(data_url):
    if not data_url or "," not in str(data_url):
        return None
    _, encoded = str(data_url).split(",", 1)
    return base64.b64decode(encoded)


def _png_bytes_to_tiff(png_bytes, dpi=300):
    image = Image.open(BytesIO(png_bytes)).convert("RGB")
    out = BytesIO()
    image.save(out, format="TIFF", dpi=(dpi, dpi), compression="tiff_deflate")
    return out.getvalue()


def _png_bytes_to_pdf(png_bytes, title="Clinical Association"):
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.lib.units import inch
    from reportlab.platypus import Image as RLImage, Paragraph, SimpleDocTemplate, Spacer
    from reportlab.lib.styles import getSampleStyleSheet

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), rightMargin=28, leftMargin=28, topMargin=28, bottomMargin=28)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(str(title), styles["Title"]),
        Spacer(1, 0.14 * inch),
    ]
    chart = RLImage(BytesIO(png_bytes))
    scale = min(doc.width / chart.imageWidth, (doc.height * 0.9) / chart.imageHeight)
    chart.drawWidth = chart.imageWidth * scale
    chart.drawHeight = chart.imageHeight * scale
    story.append(chart)
    doc.build(story)
    return buffer.getvalue()


def _clinical_static_image_path(output_dir, item):
    clinical_var = item.get("clinical_var", "clinical_association")
    image_name = item.get("data_static_image") or item.get("static_image_300dpi")
    if image_name:
        return os.path.join(output_dir, "clinical_association", image_name)
    slug = re.sub(r"[^a-z0-9]+", "_", str(clinical_var).lower()).strip("_") or "clinical_association"
    return os.path.join(output_dir, "clinical_association", "img", f"{slug}_static_data.png")


def _cache_dir(output_dir):
    cache_dir = os.path.join(output_dir, ".sigmar_cache")
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


def register_callbacks_results(app):
    app.clientside_callback(
        """
        function(nClicks, dpiValues, dpiIds) {
            const ctx = dash_clientside.callback_context;
            if (!ctx || !ctx.triggered_id) {
                return window.dash_clientside.no_update;
            }

            const trigger = ctx.triggered_id;
            const format = String(trigger.format || "png").toLowerCase();
            if (!["png", "tiff", "pdf"].includes(format)) {
                return window.dash_clientside.no_update;
            }

            const clicks = Array.isArray(nClicks) ? nClicks : [nClicks];
            if (!clicks.some((value) => Number(value || 0) > 0)) {
                return window.dash_clientside.no_update;
            }

            const clinicalVar = String(trigger.clinical_var || "clinical_association");
            let dpi = 150;
            const ids = Array.isArray(dpiIds) ? dpiIds : [];
            const values = Array.isArray(dpiValues) ? dpiValues : [];
            for (let i = 0; i < ids.length; i += 1) {
                if (ids[i] && String(ids[i].clinical_var) === clinicalVar) {
                    dpi = Number(values[i] || 150);
                    break;
                }
            }
            if (![150, 300].includes(dpi)) {
                dpi = 150;
            }
            return {
                status: "requested",
                format: format,
                clinical_var: clinicalVar,
                dpi: dpi,
                ts: Date.now()
            };
        }
        """,
        Output("ca-rendered-export-store", "data"),
        Input({"type": "ca_report_download_btn", "clinical_var": dash.ALL, "format": dash.ALL}, "n_clicks"),
        State({"type": "ca_report_dpi", "clinical_var": dash.ALL}, "value"),
        State({"type": "ca_report_dpi", "clinical_var": dash.ALL}, "id"),
        prevent_initial_call=True,
    )

    app.clientside_callback(
        """
        function(nClicks) {
            if (!nClicks) {
                return window.dash_clientside.no_update;
            }
            return {status: "requested", ts: Date.now()};
        }
        """,
        Output("ca-rendered-images-store", "data"),
        Input("btn-download-pdf", "n_clicks"),
        prevent_initial_call=True,
    )

    @app.callback(
        Output("download-html-wrapper", "data"),
        Input("btn-download-html", "n_clicks"),
        State("base_path_persistent", "data"),
        State("folder_name_persistent", "data"),
        State("selected_study_persistent", "data"),
        State("tumor_type_persistent", "data"),
        prevent_initial_call=True
    )
    def download_html_report(n_clicks, base, folder, selected_study, tumor_type):
        if not n_clicks:
            return dash.no_update

        output_dir = os.path.join(base, selected_study) if selected_study else get_clean_path(base, folder)
        cache_dir = _cache_dir(output_dir)
        cache_path = os.path.join(cache_dir, f"Subtyping_Clean_Report_{HTML_CACHE_VERSION}.html")
        source_mtime = _latest_tree_mtime(output_dir, skip_names={".sigmar_cache"})
        if _cache_is_fresh(cache_path, source_mtime):
            return dcc.send_file(cache_path)

        html_report = build_html_report(output_dir, tumor_type)
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write(html_report)
        return dcc.send_bytes(
            lambda buffer: buffer.write(html_report.encode("utf-8")),
            "Subtyping_Clean_Report.html"
        )

    @app.callback(
        Output("download-folder-wrapper", "data"),
        Input("btn-download-folder", "n_clicks"),
        State("base_path_persistent", "data"),
        State("folder_name_persistent", "data"),
        State("selected_study_persistent", "data"),
        prevent_initial_call=True
    )
    def download_folder_report(n_clicks, base, folder, selected_study):
        if not n_clicks:
            return dash.no_update

        output_dir = os.path.join(base, selected_study) if selected_study else get_clean_path(base, folder)
        if not os.path.isdir(output_dir):
            return dash.no_update

        cache_dir = _cache_dir(output_dir)
        archive_name = f"{os.path.basename(output_dir.rstrip(os.sep)) or 'subtyping_report'}.zip"
        cache_path = os.path.join(cache_dir, archive_name)
        source_mtime = _latest_tree_mtime(output_dir, skip_names={".sigmar_cache"})
        if _cache_is_fresh(cache_path, source_mtime):
            return dcc.send_file(cache_path)

        with zipfile.ZipFile(cache_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(output_dir):
                dirs[:] = [d for d in dirs if d != ".sigmar_cache"]
                for file_name in files:
                    if file_name == ".sigmar_cache":
                        continue
                    file_path = os.path.join(root, file_name)
                    arcname = os.path.relpath(file_path, output_dir)
                    zf.write(file_path, arcname)

        return dcc.send_file(cache_path)

    @app.callback(
        Output("download-pdf-wrapper", "data"),
        Input("ca-rendered-images-store", "data"),
        State("base_path_persistent", "data"),
        State("folder_name_persistent", "data"),
        State("selected_study_persistent", "data"),
        State("tumor_type_persistent", "data"),
        prevent_initial_call=True
    )
    def download_pdf_report(rendered_images, base, folder, selected_study, tumor_type):
        if not rendered_images:
            return dash.no_update

        output_dir = os.path.join(base, selected_study) if selected_study else get_clean_path(base, folder)
        pdf_bytes = build_pdf_report_bytes(output_dir, tumor_type, clinical_image_overrides={})
        return dcc.send_bytes(
            lambda buffer: buffer.write(pdf_bytes),
            "Subtyping_Clean_Report.pdf"
        )

    @app.callback(
        Output("download-figure-wrapper", "data"),
        Input("download_subtype_view_png_btn", "n_clicks"),
        Input("download_subtype_view_tiff_btn", "n_clicks"),
        Input("download_subtype_view_pdf_btn", "n_clicks"),
        Input("download_sample_view_png_btn", "n_clicks"),
        Input("download_sample_view_tiff_btn", "n_clicks"),
        Input("download_sample_view_pdf_btn", "n_clicks"),
        State("subtype-view-dpi", "value"),
        State("sample-view-dpi", "value"),
        State("base_path_persistent", "data"),
        State("folder_name_persistent", "data"),
        State("selected_study_persistent", "data"),
        prevent_initial_call=True
    )
    def download_graphic_report(n1, n2, n3, n4, n5, n6, subtype_dpi, sample_dpi, base, folder, selected_study):
        trig_id = dash.ctx.triggered_id
        if not trig_id:
            return dash.no_update

        output_dir = os.path.join(base, selected_study) if selected_study else get_clean_path(base, folder)
        json_path = os.path.join(output_dir, "dashboard_data.json")
        if not os.path.exists(json_path):
            return dash.no_update

        import json

        with open(json_path, "r") as f:
            data = json.load(f)

        mapping = {
            "download_subtype_view_png_btn": ("subtype", "png", "subtype_view.png"),
            "download_subtype_view_tiff_btn": ("subtype", "tiff", "subtype_view.tiff"),
            "download_subtype_view_pdf_btn": ("subtype", "pdf", "subtype_view.pdf"),
            "download_sample_view_png_btn": ("sample", "png", "sample_view.png"),
            "download_sample_view_tiff_btn": ("sample", "tiff", "sample_view.tiff"),
            "download_sample_view_pdf_btn": ("sample", "pdf", "sample_view.pdf"),
        }
        graphic_name, export_format, filename = mapping.get(trig_id, (None, None, None))
        if not graphic_name:
            return dash.no_update

        dpi = subtype_dpi if graphic_name == "subtype" else sample_dpi
        try:
            dpi = int(dpi)
        except Exception:
            dpi = 150
        if dpi not in (150, 300):
            dpi = 150

        payload = build_graphic_export_bytes(data, graphic_name, export_format, dpi=dpi)
        return dcc.send_bytes(lambda buffer: buffer.write(payload), filename)

    @app.callback(
        Output("ca-report-download-wrapper", "data"),
        Input("ca-rendered-export-store", "data"),
        State("base_path_persistent", "data"),
        State("folder_name_persistent", "data"),
        State("selected_study_persistent", "data"),
        prevent_initial_call=True
    )
    def download_clinical_association_graph_from_report(rendered_export, base, folder, selected_study):
        if not rendered_export or rendered_export.get("status") != "requested":
            return dash.no_update

        active_study = selected_study if selected_study else folder
        if not active_study:
            return dash.no_update

        output_dir = os.path.join(base, selected_study) if selected_study else get_clean_path(base, folder)
        summary_path = os.path.join(output_dir, "clinical_association", "clinical_association_summary.json")
        if not os.path.exists(summary_path):
            return dash.no_update

        with open(summary_path, "r") as f:
            summary = json.load(f) or []

        if not isinstance(summary, list):
            return dash.no_update

        clinical_var = rendered_export.get("clinical_var")
        export_format = str(rendered_export.get("format", "png")).lower()
        try:
            dpi = int(rendered_export.get("dpi", 150))
        except Exception:
            dpi = 150
        if dpi not in (150, 300):
            dpi = 150

        selected_item = None
        for item in summary:
            if str(item.get("clinical_var")) == str(clinical_var):
                selected_item = item
                break
        if not selected_item:
            return dash.no_update

        payload = build_clinical_association_export_bytes(
            selected_item,
            export_format=export_format,
            dpi=dpi,
            static_image_path=_clinical_static_image_path(output_dir, selected_item),
        )
        filename = f"{clinical_var}.{export_format.lower()}"
        return dcc.send_bytes(lambda buffer: buffer.write(payload), filename)

    @app.callback(
        Output("results-sort-state", "data"),
        Output("results-page-state", "data"),
        Output("results-table-wrapper", "children"),
        Input({"type": "sort_btn", "field": "final_consensus"}, "n_clicks"),
        Input({"type": "sort_btn", "field": "agreement_score"}, "n_clicks"),
        Input("results-page-prev", "n_clicks"),
        Input("results-page-next", "n_clicks"),
        State("results-sort-state", "data"),
        State("results-page-state", "data"),
        State("base_path_persistent", "data"),
        State("folder_name_persistent", "data"),
        State("selected_study_persistent", "data"),
        prevent_initial_call=False
    )
    def update_results_table(final_clicks, agreement_clicks, prev_clicks, next_clicks,
                             sort_state, page_state, base, folder, selected_study):
        triggered = dash.ctx.triggered_id
        output_dir = os.path.join(base, selected_study) if selected_study else get_clean_path(base, folder)
        json_path = os.path.join(output_dir, "dashboard_data.json")
        if not os.path.exists(json_path):
            return dash.no_update, dash.no_update, dash.no_update

        import json

        with open(json_path, "r") as f:
            data = json.load(f)

        current_field = (sort_state or {}).get("field", "default")
        current_order = (sort_state or {}).get("order", "asc")
        page = int(page_state or 0)

        if isinstance(triggered, dict) and triggered.get("type") == "sort_btn":
            field = triggered.get("field", "default")
            if field == current_field:
                current_order = "desc" if current_order == "asc" else "asc"
            else:
                current_field = field
                current_order = "asc"
            page = 0                                   # a new order starts from the top
        elif triggered == "results-page-prev":
            page = max(0, page - 1)
        elif triggered == "results-page-next":
            page = page + 1

        new_state = {"field": current_field, "order": current_order}
        return new_state, page, _build_results_table(data, sort_field=current_field,
                                                     sort_order=current_order, page=page)

    @app.callback(
        Output("download-csv-wrapper", "data"),
        Input("btn-download-csv", "n_clicks"),
        State("base_path_persistent", "data"),
        State("folder_name_persistent", "data"),
        State("selected_study_persistent", "data"),
        prevent_initial_call=True
    )
    def download_csv_report(n_clicks, base, folder, selected_study):
        if not n_clicks:
            return dash.no_update

        output_dir = os.path.join(base, selected_study) if selected_study else get_clean_path(base, folder)
        json_path = os.path.join(output_dir, "dashboard_data.json")
        report_path = os.path.join(output_dir, "final_complete_summary.txt")

        if os.path.exists(json_path):
            import json
            import pandas as pd

            with open(json_path, "r") as f:
                data = json.load(f)

            df = pd.json_normalize(data)
            if "primary_subtype" in df.columns:
                df["final consensus"] = df["primary_subtype"]
            else:
                df["final consensus"] = "Uncertain"

            if "confidence" in df.columns:
                df["agreement score"] = df["confidence"]
                df["agreement score pct"] = (df["confidence"].fillna(0).astype(float) * 100).round(2)
            else:
                df["agreement score"] = 0
                df["agreement score pct"] = 0

            drop_cols = {
                "primary_subtype",
                "confidence",
                "details.ntp",
                "details.gsea",
                "details.consensus",
                "details.pce_pearson",
                "details.breast_aims",
                "details.breast_sspbc",
                "details.tmp_summary",
            }
            df = df.drop(columns=[c for c in drop_cols if c in df.columns], errors="ignore")

            preferred_cols = [
                "Samples",
                "ntp_pred",
                "ss_gsea_pred",
                "consensus_ov_pred",
                "breast_aims_pred",
                "breast_sspbc_pred",
                "pce_pearson",
                "pce_cosine",
                "pce_euclidean",
                "result_aklimate",
                "result_jadbio",
                "result_skgrid",
                "result_subscope",
                "result_cloudforest",
                "cms_rf_pred",
                "cms_ssp_pred",
                "cms_caller_pred",
            ]
            final_cols = [
                "final consensus",
                "agreement score",
                "agreement score pct",
            ]
            available_cols = [c for c in preferred_cols if c in df.columns]
            available_final_cols = [c for c in final_cols if c in df.columns]
            remaining_cols = [c for c in df.columns if c not in available_cols and c not in available_final_cols]
            df = df[available_cols + remaining_cols + available_final_cols]
            return dcc.send_data_frame(df.to_csv, "subtyping_summary.csv", index=False)

        if os.path.exists(report_path):
            import pandas as pd

            df = pd.read_csv(report_path, sep="\t")
            return dcc.send_data_frame(df.to_csv, "subtyping_summary.csv", index=False)

        return dash.no_update

    @app.callback(
        Output("clinical-association-content", "children"),
        Input("report-tabs", "active_tab"),
        State("base_path_persistent", "data"),
        State("folder_name_persistent", "data"),
        State("selected_study_persistent", "data"),
        prevent_initial_call=False
    )
    def load_clinical_association_tab(active_tab, base, folder, selected_study):
        if active_tab != "clinical-association":
            return dash.no_update

        output_dir = os.path.join(base, selected_study) if selected_study else get_clean_path(base, folder)
        clinical_summary = _load_clinical_association_summary(output_dir)
        if not clinical_summary:
            return dbc.Alert(
                "No clinical association results are available yet. Run the analysis from the Clinical Association page first.",
                color="info",
                className="mb-3",
            )

        return [
            _clinical_association_card(item)
            for item in clinical_summary
        ]
