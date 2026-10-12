import dash
from dash import Input, Output, State, html, dcc, ctx
import dash_bootstrap_components as dbc
import subprocess
import os
import shutil
import time
import json
import resource
from datetime import datetime
from config import PROJECT_ROOT, SCRIPT_DIR, UPLOAD_FOLDER_TEMP
from scripts.function import read_table_preview, read_table_headers

GDA_TMP_ROOT = os.path.join(PROJECT_ROOT, "utilities", "gdan-tmp-models")
GDA_DOCKER_TMP = os.path.join(GDA_TMP_ROOT, "docker_tmp")
GDA_SHARED_DATA = os.path.join(GDA_TMP_ROOT, "shared_data")

# TMP is OPTIONAL only for these "divided" tumors, where its integrative
# scheme doesn't align with the centroid subtypes (see monitor_steps' step-5
# skip logic below). For every other tumor TMP always runs regardless of the
# "Run GDAN-TMP models" toggle, so that toggle is only shown for tumors in
# this list (see toggle_tmp_section) - showing a checkbox with no effect
# elsewhere would be misleading.
# BRCA is merged (same PAM50 taxonomy for centroids and GDAN-TMP); its validation
# and weighting are fitted on the external SCAN-B cohort (see merge.R).
DIVIDED_TUMORS = ["coad", "coadread", "read", "gbm", "luad", "lusc", "meso", "pdac", "hnsc", "hnscc"]

# Every step's status_row() id (see layout_analysis.py), in pipeline order -
# used by start_prediction_pipeline() to reset every step's spinner/check/
# error/skipped icon back to hidden when a new run starts, so a rerun
# doesn't keep showing the previous run's ✅/❌ on steps it hasn't reached
# yet (or won't reach again this run, e.g. TMP/cons_ov/cms/breast_subtype
# being conditionally skipped).
STATUS_METHOD_IDS = ["prepare", "ntp", "ssgsea", "centroid", "tmp", "cons_ov", "cms", "breast_subtype", "finalize"]

# (label, output subfolder inside the study dir - None for steps that don't
# have their own subfolder) for each method, used to build run_report.*.
METHOD_OUTPUT_INFO = {
    "prepare": ("Preparing Data", None),
    "ntp": ("Nearest Template Prediction (NTP)", "NTP"),
    "ssgsea": ("Single Sample GSEA (ssGSEA)", "ssGSEA"),
    "centroid": ("Centroid Correlation", "Centroid_Correlation"),
    "tmp": ("Tumor Molecular Pathology (TMP)", "TMP"),
    "cons_ov": ("Consensus Ovary", "Consensus_OV"),
    "cms": ("CMS", "CMS"),
    "breast_subtype": ("Breast Subtype", "breast_subtype"),
    "finalize": ("Finalizing & Reporting", None),
}


def _html_escape(value):
    return (str(value)
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _write_run_report(out_dir, tumor, folder_name, counts_gene_column, clinical_sample_column,
                       run_tmp_requested, step_stats, pipeline_start):
    """Writes run_report.txt/.json/.html into <out_dir>/report/ once the
    whole pipeline finishes - what tumor/parameters were used, which
    methods ran and where their output landed, and how long/how much
    CPU+RAM each step (and the run as a whole) took. Best-effort: never
    raises, since this runs right after the pipeline already succeeded and
    shouldn't be able to turn a completed run into a failed one.
    """
    try:
        report_dir = os.path.join(out_dir, "report")
        os.makedirs(report_dir, exist_ok=True)

        total_elapsed = time.time() - (pipeline_start or time.time())
        peak_rss_kb = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss  # Linux: KB

        norm_meta = {}
        norm_meta_path = os.path.join(out_dir, "normalization_metadata.json")
        if os.path.exists(norm_meta_path):
            try:
                with open(norm_meta_path) as f:
                    norm_meta = json.load(f)
            except Exception:
                norm_meta = {}
        normalization_ran = bool(norm_meta) or os.path.exists(os.path.join(out_dir, "norm_data.csv"))
        # normalize.R writes what it detected/did (input type, size-factor
        # range, clipping, batch correction) to norm_method.txt.
        norm_method_lines = []
        norm_method_path = os.path.join(out_dir, "norm_method.txt")
        if os.path.exists(norm_method_path):
            try:
                with open(norm_method_path) as f:
                    norm_method_lines = [ln.strip() for ln in f if ln.strip()]
            except Exception:
                norm_method_lines = []

        methods_run = []
        for method_id, (label, subfolder) in METHOD_OUTPUT_INFO.items():
            stat = step_stats.get(method_id)
            if not stat:
                continue
            out_path = os.path.join(out_dir, subfolder) if subfolder else out_dir
            methods_run.append({
                "method": label,
                "duration_sec": stat.get("duration_sec"),
                "cpu_time_sec": stat.get("cpu_time_sec"),
                "output_path": out_path if (not subfolder or os.path.isdir(out_path)) else None,
            })

        # Everything else worth pointing at, if it actually got written.
        other_outputs = {}
        for label, name in [
            ("Consensus report (HTML)", "report.html"),
            ("Combined summary (TSV)", "final_complete_summary.txt"),
            ("Dashboard data (JSON)", "dashboard_data.json"),
            ("Uploaded counts", "counts.csv"),
            ("Uploaded clinical data", "annotation.csv"),
            ("Normalized counts", "norm_data.csv"),
        ]:
            candidate = os.path.join(out_dir, name)
            if os.path.exists(candidate):
                other_outputs[label] = candidate

        report = {
            "study_name": folder_name,
            "tumor_type": tumor,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "parameters": {
                "counts_gene_column": counts_gene_column,
                "clinical_sample_column": clinical_sample_column,
                "normalization_run": normalization_ran,
                "batch_correction_enabled": norm_meta.get("batch_correction_enabled", False),
                "batch_correction_column": norm_meta.get("batch_column"),
                "normalization_method": norm_method_lines,
                "gdan_tmp_requested": bool(run_tmp_requested),
            },
            "performance": {
                "total_duration_sec": round(total_elapsed, 1),
                "peak_memory_mb_all_steps": round(peak_rss_kb / 1024, 1) if peak_rss_kb else None,
                "note": "peak_memory_mb_all_steps is the high-water mark across every R "
                        "step in this run (getrusage can't split it out per step); "
                        "duration_sec/cpu_time_sec below are per step and accurate.",
            },
            "methods_run": methods_run,
            "other_outputs": other_outputs,
            "output_root": out_dir,
            "report_dir": report_dir,
        }

        with open(os.path.join(report_dir, "run_report.json"), "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        lines = [
            f"SiGMaR Analysis Report - {folder_name}",
            "=" * 50,
            f"Generated: {report['generated_at']}",
            f"Tumor type: {tumor}",
            "",
            "Parameters",
            "-" * 50,
            f"Gene column: {counts_gene_column}",
            f"Sample ID column: {clinical_sample_column}",
            f"Normalization run: {'yes' if normalization_ran else 'no'}",
        ]
        if normalization_ran:
            lines.append(
                f"Batch correction: "
                f"{'yes (column: ' + str(norm_meta.get('batch_column')) + ')' if norm_meta.get('batch_correction_enabled') else 'no'}"
            )
            for ln in norm_method_lines:
                lines.append(f"  {ln}")
        lines += [
            f"GDAN-TMP requested: {'yes' if run_tmp_requested else 'no'}",
            "",
            "Performance",
            "-" * 50,
            f"Total analysis time: {total_elapsed:.1f}s",
            f"Peak memory (all steps, high-water mark): "
            f"{round(peak_rss_kb / 1024, 1) if peak_rss_kb else 'n/a'} MB",
            "",
            "Methods run",
            "-" * 50,
        ]
        for m in methods_run:
            duration = f"{m['duration_sec']:.1f}s" if m["duration_sec"] is not None else "n/a"
            cpu = f"{m['cpu_time_sec']:.1f}s" if m["cpu_time_sec"] is not None else "n/a"
            lines.append(f"- {m['method']}: {duration} wall / {cpu} CPU -> {m['output_path'] or '(no dedicated output folder)'}")
        lines += ["", "Other outputs", "-" * 50]
        for label, path in other_outputs.items():
            lines.append(f"- {label}: {path}")
        lines += ["", f"Output root: {out_dir}"]

        with open(os.path.join(report_dir, "run_report.txt"), "w") as f:
            f.write("\n".join(lines) + "\n")

        # --- HTML ---
        method_rows = []
        for m in methods_run:
            duration = f"{m['duration_sec']:.1f}s" if m["duration_sec"] is not None else "n/a"
            cpu = f"{m['cpu_time_sec']:.1f}s" if m["cpu_time_sec"] is not None else "n/a"
            path_html = _html_escape(m["output_path"]) if m["output_path"] else "<em>no dedicated output folder</em>"
            method_rows.append(
                f"<tr><td>{_html_escape(m['method'])}</td><td>{duration}</td><td>{cpu}</td><td>{path_html}</td></tr>"
            )
        other_rows = "".join(
            f"<tr><td>{_html_escape(label)}</td><td>{_html_escape(path)}</td></tr>"
            for label, path in other_outputs.items()
        )
        batch_html = (
            ("yes (column: " + _html_escape(norm_meta.get("batch_column")) + ")")
            if norm_meta.get("batch_correction_enabled") else "no"
        ) if normalization_ran else "n/a"

        html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>SiGMaR Analysis Report - {_html_escape(folder_name)}</title>
<style>
  body {{ font-family: -apple-system, Arial, sans-serif; color: #0f172a; background: #f8fafc; margin: 0; padding: 32px; }}
  main {{ max-width: 900px; margin: 0 auto; background: #ffffff; border-radius: 12px; padding: 32px 40px; box-shadow: 0 4px 16px rgba(15,23,42,0.08); }}
  h1 {{ margin: 0 0 4px; color: #0F766E; }}
  .meta {{ color: #475569; margin: 0 0 24px; }}
  h2 {{ color: #0F766E; border-bottom: 2px solid #CCFBF1; padding-bottom: 6px; margin-top: 32px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
  th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #e2e8f0; font-size: 14px; }}
  th {{ color: #475569; font-weight: 600; background: #f1f5f9; }}
  td em {{ color: #94a3b8; }}
  .stat-grid {{ display: flex; gap: 24px; margin-top: 8px; flex-wrap: wrap; }}
  .stat {{ background: #ECFEFF; border-radius: 8px; padding: 12px 20px; min-width: 160px; }}
  .stat .value {{ font-size: 22px; font-weight: 700; color: #0F766E; }}
  .stat .label {{ font-size: 12px; color: #475569; }}
  .note {{ font-size: 12px; color: #94a3b8; margin-top: 8px; }}
  code {{ background: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-size: 13px; }}
</style>
</head>
<body>
<main>
  <h1>SiGMaR Analysis Report</h1>
  <p class="meta">Study: <strong>{_html_escape(folder_name)}</strong> &middot; Generated {_html_escape(report['generated_at'])}</p>

  <h2>Parameters</h2>
  <table>
    <tr><th>Tumor type</th><td>{_html_escape(tumor)}</td></tr>
    <tr><th>Gene column</th><td>{_html_escape(counts_gene_column)}</td></tr>
    <tr><th>Sample ID column</th><td>{_html_escape(clinical_sample_column)}</td></tr>
    <tr><th>Normalization run</th><td>{'yes' if normalization_ran else 'no'}{('<br><small>' + '<br>'.join(_html_escape(ln) for ln in norm_method_lines) + '</small>') if norm_method_lines else ''}</td></tr>
    <tr><th>Batch correction</th><td>{batch_html}</td></tr>
    <tr><th>GDAN-TMP requested</th><td>{'yes' if run_tmp_requested else 'no'}</td></tr>
  </table>

  <h2>Performance</h2>
  <div class="stat-grid">
    <div class="stat"><div class="value">{total_elapsed:.1f}s</div><div class="label">Total analysis time</div></div>
    <div class="stat"><div class="value">{round(peak_rss_kb / 1024, 1) if peak_rss_kb else 'n/a'} MB</div><div class="label">Peak memory (all steps)</div></div>
  </div>
  <p class="note">Peak memory is a high-water mark across every R step in this run (can't be split out per step); per-step duration/CPU time below are accurate.</p>

  <h2>Methods run</h2>
  <table>
    <tr><th>Method</th><th>Duration</th><th>CPU time</th><th>Output path</th></tr>
    {''.join(method_rows)}
  </table>

  <h2>Other outputs</h2>
  <table>
    <tr><th>File</th><th>Path</th></tr>
    {other_rows}
  </table>

  <p class="note">Output root: <code>{_html_escape(out_dir)}</code></p>
</main>
</body>
</html>
"""
        with open(os.path.join(report_dir, "run_report.html"), "w") as f:
            f.write(html)
    except Exception:
        pass

def get_clean_path(base_path, folder_name):
        invalid_keywords = ["Errore GUI", "Incolla il percorso", "non disponibile", "None"]
        folder_clean = str(folder_name).strip() if folder_name and str(folder_name).strip() != "" else "default_analysis"
        base_str = str(base_path)
        is_invalid = any(kw in base_str for kw in invalid_keywords) or not base_path
        if is_invalid:
            final_base = os.path.abspath(os.path.join(PROJECT_ROOT, "uploads", "results"))
        else:
            final_base = os.path.abspath(base_str)
        full_path = os.path.join(final_base, folder_clean)
        os.makedirs(full_path, exist_ok=True)
        return full_path

# Monitoraggio globale del processo R
current_process = {
    "proc": None, "step": 0, "cmd": None,
    # For run_report.txt/.json (see _write_run_report): wall-clock/CPU time
    # per completed step, when the whole pipeline started, and a rusage
    # snapshot taken right before each subprocess launches (diffed against
    # the snapshot after it exits to get that step's CPU time).
    "stats": {}, "pipeline_start": None, "step_start": None, "rusage_before": None,
}

# Tumors for which the optional method weighting is validated (validation cohort
# independent of the reference centroid) AND shows a gain over the equal vote.
WEIGHTING_TUMORS = {"luad", "lusc", "pdac", "paad", "brca", "brca_pam50", "breast"}


def cleanup_temp_uploads():
    for folder in ["counts", "annotation"]:
        folder_path = os.path.join(UPLOAD_FOLDER_TEMP, folder)
        shutil.rmtree(folder_path, ignore_errors=True)
        os.makedirs(folder_path, exist_ok=True)


def cleanup_tmp_runtime():
    for path in [
        GDA_DOCKER_TMP,
        os.path.join(GDA_SHARED_DATA, "tmp"),
    ]:
        os.makedirs(path, exist_ok=True)
        for entry in os.listdir(path):
            entry_path = os.path.join(path, entry)
            shutil.rmtree(entry_path, ignore_errors=True) if os.path.isdir(entry_path) else os.remove(entry_path)

    shared_data_dir = os.path.join(GDA_SHARED_DATA, "data")
    os.makedirs(shared_data_dir, exist_ok=True)
    for entry in os.listdir(shared_data_dir):
        entry_path = os.path.join(shared_data_dir, entry)
        if os.path.isdir(entry_path):
            shutil.rmtree(entry_path, ignore_errors=True)
        else:
            os.remove(entry_path)


def _normalize_name(value):
    return str(value).strip().lower()


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
        if "gene" in _normalize_name(col):
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
        if "sample" in _normalize_name(col):
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


def _materialize_and_standardize_csv(source_path, target_path, selected_column, detector):
    """Read the freshly uploaded source once, detect/reorder the id column,
    and write the standardized CSV once. Replaces the old two-step
    materialize-then-standardize path, which read and wrote the same
    (potentially large) count matrix twice back to back for no reason on
    every fresh upload."""
    if not source_path or not os.path.exists(source_path):
        return None
    df = read_table_preview(source_path, nrows=None)
    columns = [str(c) for c in df.columns]
    chosen = None
    if columns:
        candidate = selected_column if selected_column in columns else detector(columns)
        if candidate in columns:
            chosen = candidate
            ordered_columns = [chosen] + [c for c in columns if c != chosen]
            df = df.loc[:, ordered_columns]

    df.to_csv(target_path, index=False)
    if os.path.abspath(source_path) != os.path.abspath(target_path):
        try:
            os.remove(source_path)
        except OSError:
            pass
    return chosen


def _copy_input_to_output(source_path, output_dir, filename):
    if not source_path or not output_dir or not os.path.exists(source_path):
        return False
    os.makedirs(output_dir, exist_ok=True)
    target_path = os.path.join(output_dir, filename)
    if os.path.abspath(source_path) == os.path.abspath(target_path):
        return True
    shutil.copy2(source_path, target_path)
    return True


def _needs_refresh(source_path, target_path):
    if not source_path or not os.path.exists(source_path):
        return False
    if not target_path or not os.path.exists(target_path):
        return True
    return os.path.getmtime(source_path) > os.path.getmtime(target_path) + 0.5


def _first_column_matches(path, selected_column):
    if not selected_column or not path or not os.path.exists(path) or os.path.getsize(path) == 0:
        return True
    try:
        columns = read_table_headers(path)
    except Exception:
        return False
    return bool(columns) and str(columns[0]) == str(selected_column)


def _prepare_uploaded_inputs(output_dir, counts_gene_column=None, clinical_sample_column=None):
    counts_folder = os.path.join(UPLOAD_FOLDER_TEMP, "counts")
    annotation_folder = os.path.join(UPLOAD_FOLDER_TEMP, "annotation")
    output_counts_path = os.path.join(output_dir, "counts.csv")
    output_annotation_path = os.path.join(output_dir, "annotation.csv")
    counts_source_path = _find_uploaded_source_file(counts_folder, "counts.csv")
    annotation_source_path = _find_uploaded_source_file(annotation_folder, "annotation.csv")

    if _needs_refresh(counts_source_path, output_counts_path):
        _materialize_and_standardize_csv(counts_source_path, output_counts_path, counts_gene_column, _detect_gene_column)
    elif os.path.exists(output_counts_path) and not _first_column_matches(output_counts_path, counts_gene_column):
        _standardize_table(output_counts_path, counts_gene_column, _detect_gene_column)

    annotation_arg = ""
    if _needs_refresh(annotation_source_path, output_annotation_path):
        _materialize_and_standardize_csv(annotation_source_path, output_annotation_path, clinical_sample_column, _detect_sample_column)
    elif os.path.exists(output_annotation_path) and not _first_column_matches(output_annotation_path, clinical_sample_column):
        _standardize_table(output_annotation_path, clinical_sample_column, _detect_sample_column)

    if os.path.exists(output_annotation_path) and os.path.getsize(output_annotation_path) > 0:
        annotation_arg = output_annotation_path

    return output_counts_path, annotation_arg

def register_callbacks_analysis(app):

    # Only tumors in DIVIDED_TUMORS actually respect the "Run GDAN-TMP
    # models" toggle (see monitor_steps below); for every other tumor TMP
    # always runs, so hide the toggle there instead of showing a checkbox
    # with no effect.
    @app.callback(
        Output("tmp_toggle_section", "style"),
        Input("tumor_type_persistent", "data"),
    )
    def toggle_tmp_section(tumor_type):
        if str(tumor_type or "").lower() in DIVIDED_TUMORS:
            return {"display": "block"}
        return {"display": "none"}

    # =========================================================
    # 1. NORMALIZZAZIONE (Sincrona)
    # =========================================================

    @app.callback(
        Output("batch_correction_tick", "options"),
        Input("url", "pathname"), 
        State("base_path_persistent", "data")
    )
    def validate_batch_column(path, base_path):
        # Percorso del file caricato
        annot_folder = os.path.join(UPLOAD_FOLDER_TEMP, "annotation")
        annot_path = _find_uploaded_source_file(annot_folder, "annotation.csv")
        
        label_text = "Enable Batch Correction"
        is_disabled = True
        
        if annot_path and os.path.exists(annot_path):
            try:
                # Leggiamo solo l'header per non caricare file pesanti in memoria.
                # Non serve una colonna chiamata letteralmente "batch": qualsiasi
                # colonna clinica va bene, l'utente la sceglie dal dropdown sotto
                # (populate_batch_column_options gia' elenca tutte le colonne e
                # preseleziona "batch" solo se esiste, senza richiederlo).
                df_check_columns = read_table_headers(annot_path)

                if df_check_columns:
                    is_disabled = False
                    label_text = "Enable Batch Correction (Ready)"
                else:
                    label_text = "Batch Correction (annotation.csv has no columns)"
                    is_disabled = True
            except Exception as e:
                label_text = f"Error reading annotation.csv"
                is_disabled = True
        else:
            label_text = "Batch Correction (No annotation.csv found)"
            is_disabled = True
        
        return [{
            "label": label_text, 
            "value": 1, 
            "disabled": is_disabled
        }]

    @app.callback(
        Output("batch_column_collapse", "is_open"),
        Input("batch_correction_tick", "value"),
        prevent_initial_call=False
    )
    def toggle_batch_column_box(batch_val):
        return bool(batch_val and 1 in batch_val)

    # Safety net for the visibility the layout already decided (serve_layout_analysis):
    # re-fires whenever the stored tumor type changes, e.g. the user goes back, picks a
    # different tumor and returns to this page without a full page rebuild. The switch is
    # left OFF: the equal vote is the documented default and the weighting is opt-in.
    @app.callback(
        Output("weighting_toggle_section", "style"),
        Input("tumor_type_persistent", "data"),
    )
    def configure_weighting_switch(tumor):
        if str(tumor or "").strip().lower() in WEIGHTING_TUMORS:
            return {"display": "block"}
        return {"display": "none"}

    @app.callback(
        [Output("batch_column_select", "options"),
         Output("batch_column_select", "value"),
         Output("batch_column_select", "disabled"),
         Output("batch_column_persistent", "data")],
        Input("url", "pathname"),
        [State("batch_column_persistent", "data")],
        prevent_initial_call=False
    )
    def populate_batch_column_options(path, persisted_value):
        annot_folder = os.path.join(UPLOAD_FOLDER_TEMP, "annotation")
        annot_path = _find_uploaded_source_file(annot_folder, "annotation.csv")
        if not annot_path or not os.path.exists(annot_path):
            return [], None, True, None

        try:
            batch_columns = read_table_headers(annot_path)
            options = [{"label": str(col), "value": str(col)} for col in batch_columns]
            default_value = None
            if persisted_value in batch_columns:
                default_value = persisted_value
            elif "batch" in [str(col).strip().lower() for col in batch_columns]:
                for col in batch_columns:
                    if str(col).strip().lower() == "batch":
                        default_value = str(col)
                        break
            elif batch_columns:
                default_value = str(batch_columns[0])
            return options, default_value, False, default_value
        except Exception:
            return [], None, True, None

    @app.callback(
        Output("batch_column_persistent", "data", allow_duplicate=True),
        Input("batch_column_select", "value"),
        prevent_initial_call=True
    )
    def sync_batch_column(batch_column):
        return batch_column

    @app.callback(
        Output("normalize_output", "children"),
        Input("normalize_btn", "n_clicks"),
        [State("base_path_persistent", "data"),
         State("folder_name_persistent", "data"),
         State("batch_correction_tick", "value"),
         State("batch_column_persistent", "data"),
         State("counts_gene_column_persistent", "data"),
         State("clinical_sample_column_persistent", "data")],
        running=[
            (Output("normalize_btn", "disabled"), True, False),
            (Output("btn-run-annotation", "disabled"), True, False),
        ],
        prevent_initial_call=True
    )

    def run_normalization(n, base_path, folder_name, batch_val, batch_column, counts_gene_column, clinical_sample_column):
        if not n: return ""
        output_dir = get_clean_path(base_path, folder_name)
        batch_on = bool(batch_val and 1 in batch_val)
        batch_bool = "TRUE" if batch_on else "FALSE"
        counts_path, annotation_arg = _prepare_uploaded_inputs(
            output_dir,
            counts_gene_column=counts_gene_column,
            clinical_sample_column=clinical_sample_column,
        )

        # Recorded so run_report.txt/.json (written once the prediction
        # pipeline finishes - see _write_run_report) can say whether/how
        # batch correction was used, since this callback is the only place
        # that actually knows.
        try:
            with open(os.path.join(output_dir, "normalization_metadata.json"), "w") as f:
                json.dump({
                    "ran_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "batch_correction_enabled": batch_on,
                    "batch_column": batch_column if batch_on else None,
                }, f, indent=2)
        except OSError:
            pass

        cmd = [
            "Rscript",
            os.path.join(SCRIPT_DIR, "normalize.R"),
            counts_path,
            annotation_arg,
            batch_bool,
            output_dir,
            batch_column or "",
        ]
        try:
            completed = subprocess.run(cmd, capture_output=True, text=True, check=True)
            stdout = (completed.stdout or "").strip()
            # normalize.R prints one line summarising what it detected and did
            # (input type, size factors, clipping, batch correction); it is
            # prefixed with WARNING: when the matrix was not normalized as
            # raw counts (log-scale passthrough, clipped negatives).
            if "WARNING:" in stdout:
                return dbc.Alert(stdout, color="warning", dismissable=True)
            return dbc.Alert("Normalization completed!", color="success", dismissable=True)
        except subprocess.CalledProcessError as e:
            stderr_lines = (e.stderr or "").strip().splitlines()
            error_text = next((line for line in reversed(stderr_lines) if line.startswith("Error")), None)
            return dbc.Alert(f"R Error: {error_text or (e.stderr or 'Normalization failed')}", color="danger", dismissable=True)

    # =========================================================
    # 2. PREDICTION PIPELINE (Asincrona con Polling)
    # =========================================================
    
    _other_step_icon_outputs = [
        Output(f"{kind}-{mid}", "style", allow_duplicate=True)
        for mid in STATUS_METHOD_IDS if mid != "prepare"
        for kind in ("spin", "check", "err", "skip")
    ] + [Output("skip-prepare", "style", allow_duplicate=True)]

    @app.callback(
        [Output("progress-interval", "disabled"),
         Output("analysis-step-tracker", "data"),
         Output("btn-run-annotation", "disabled"),
         Output("normalize_btn", "disabled"),
         Output("spin-prepare", "style"),
         Output("check-prepare", "style"),
         Output("err-prepare", "style"),
         *_other_step_icon_outputs,
         Output("view_error_details_btn", "style"),
         Output("last_step_error", "data")],
        Input("btn-run-annotation", "n_clicks"),
        prevent_initial_call=True
    )
    def start_prediction_pipeline(n):
        hidden = {"display": "none"}
        # Every step past "prepare" hasn't started yet on a fresh run - wipe
        # any ✅/❌/Skipped left over from a previous run so they don't sit
        # there stale while the new run is in progress. Same for a leftover
        # "View Error Details" button/error from a previous failed run.
        reset_rest = [hidden] * len(_other_step_icon_outputs)
        if n:
            # Fresh run_report.txt/.json timing - see _write_run_report.
            current_process["stats"] = {}
            current_process["pipeline_start"] = time.time()
            return (False, 1, True, True, {"display": "inline-block"}, hidden, hidden, *reset_rest, hidden, None)
        return (True, 0, False, False, hidden, hidden, hidden, *reset_rest, hidden, None)

    @app.callback(
        [Output("error_details_modal", "is_open"),
         Output("error_details_modal_title", "children"),
         Output("error_details_modal_body", "children"),
         Output("error_details_modal_path", "children")],
        Input("view_error_details_btn", "n_clicks"),
        State("last_step_error", "data"),
        prevent_initial_call=True,
    )
    def open_error_details_modal(n_clicks, error_data):
        if not n_clicks or not error_data:
            raise dash.exceptions.PreventUpdate
        method = error_data.get("method", "step")
        text = error_data.get("text") or "No details available."
        path = error_data.get("path") or ""
        return True, f"Error in {method}", text, (f"Full log saved to: {path}" if path else "")

    @app.callback(
        Output({"type": "nav_btn", "index": "back_to_upload_btn"}, "disabled"),
        [Input("analysis-step-tracker", "data"),
         Input("normalize_btn", "disabled"),
         Input("btn-run-annotation", "disabled")],
        prevent_initial_call=False
    )
    def toggle_back_to_upload(step, normalize_disabled, run_disabled):
        return bool((step or 0) > 0 or normalize_disabled or run_disabled)

    @app.callback(
        [
            # Step 1: Preparing data (3 Output)
            Output("spin-prepare", "style", allow_duplicate=True), Output("check-prepare", "style", allow_duplicate=True), Output("err-prepare", "style", allow_duplicate=True),
            # Step 1-4 (12 Output)
            Output("spin-ntp", "style"), Output("check-ntp", "style"), Output("err-ntp", "style"),
            Output("spin-ssgsea", "style"), Output("check-ssgsea", "style"), Output("err-ssgsea", "style"),
            Output("spin-centroid", "style"), Output("check-centroid", "style"), Output("err-centroid", "style"),
            Output("spin-tmp", "style"), Output("check-tmp", "style"), Output("err-tmp", "style"),
            # Step 5: Consensus (4 Output)
            Output("spin-cons_ov", "style"), Output("check-cons_ov", "style"), Output("err-cons_ov", "style"), Output("skip-cons_ov", "style"),
            # Step 6: CMS (4 Output)
            Output("spin-cms", "style"), Output("check-cms", "style"), Output("err-cms", "style"), Output("skip-cms", "style"),
            # Step 7: Breast subtype (4 Output)
            Output("spin-breast_subtype", "style"), Output("check-breast_subtype", "style"), Output("err-breast_subtype", "style"), Output("skip-breast_subtype", "style"),
            # Step 8: Finalize (3 Output)
            Output("spin-finalize", "style"), Output("check-finalize", "style"), Output("err-finalize", "style"),
            # UI & Navigation (4 Output - rimosso results-anchor)
            Output("analysis-step-tracker", "data", allow_duplicate=True),
            Output("ntp-status-badge", "children"),
            Output("btn-run-annotation", "disabled", allow_duplicate=True),
            Output("normalize_btn", "disabled", allow_duplicate=True),
            Output({"type": "nav_btn", "index": "analysis_results_btn"}, "disabled"),
            # TMP skip badge (index 35) - appended, not inserted, so the
            # hardcoded res[n] indices used throughout this callback for
            # every other step stay valid. Same for the two after it.
            Output("skip-tmp", "style"),
            Output("view_error_details_btn", "style", allow_duplicate=True),
            Output("last_step_error", "data", allow_duplicate=True),
        ],
        Input("progress-interval", "n_intervals"),
        [State("analysis-step-tracker", "data"), 
         State("folder_name_persistent", "data"), 
         State("base_path_persistent", "data"), 
         State("tumor_type_persistent", "data"),
         State("counts_gene_column_persistent", "data"),
         State("clinical_sample_column_persistent", "data"),
         State("run_tmp_tick", "value"),
         State("weighting_tick", "value")],
        prevent_initial_call=True
    )
    def monitor_steps(n, step, folder, base, tumor, counts_gene_column, clinical_sample_column, run_tmp, weighting):
        if step == 0: raise dash.exceptions.PreventUpdate

        methods = {1: "prepare", 2: "ntp", 3: "ssgsea", 4: "centroid", 5: "tmp", 6: "cons_ov", 7: "cms", 8: "breast_subtype", 9: "finalize"}
        method_name = methods.get(step)
        
        # Inizializziamo 38 Output (da 0 a 37 - 36 originali + view_error_details_btn/last_step_error)
        res = [dash.no_update] * 38
        start_idx_map = {1:0, 2:3, 3:6, 4:9, 5:12, 6:15, 7:19, 8:23, 9:27}
        idx = start_idx_map.get(step)

        if current_process["proc"] is None or current_process["step"] != step:
            out_dir = get_clean_path(base, folder)
            if step == 1:
                step_t0 = time.time()
                try:
                    _prepare_uploaded_inputs(
                        out_dir,
                        counts_gene_column=counts_gene_column,
                        clinical_sample_column=clinical_sample_column,
                    )
                    res[0], res[1], res[30] = {"display": "none"}, {"display": "inline"}, 2
                    res[31] = dbc.Badge("Phase: ntp...", color="warning")
                    # Runs synchronously in this same Python process (no
                    # subprocess), so only wall time is meaningful here -
                    # for run_report.txt/.json (see _write_run_report).
                    current_process["stats"]["prepare"] = {
                        "duration_sec": time.time() - step_t0, "cpu_time_sec": None,
                    }
                except Exception as exc:
                    res[0], res[2] = {"display": "none"}, {"display": "inline"}
                    res[30], res[32], res[33] = 0, False, False
                    res[31] = dbc.Badge(f"Error preparing data: {str(exc)[:80]}", color="danger")
                    full_text = repr(exc)
                    log_path = os.path.join(out_dir, "logs", "prepare_error.log")
                    try:
                        os.makedirs(os.path.dirname(log_path), exist_ok=True)
                        with open(log_path, "w") as f:
                            f.write(f"Step: prepare\n\n{full_text}")
                    except OSError:
                        pass
                    res[36] = {"display": "inline-block"}
                    res[37] = {"method": "prepare", "path": log_path, "text": full_text}
                return res

            if step == 6 and str(tumor).lower() not in ["ov", "ovary"]:
                res[15], res[16], res[17], res[18], res[30] = {"display": "none"}, {"display": "none"}, {"display": "none"}, {"display": "inline"}, 7
                return res
            if step == 7 and str(tumor).lower() not in ["coad", "coadread", "read"]:
                res[19], res[20], res[21], res[22], res[30] = {"display": "none"}, {"display": "none"}, {"display": "none"}, {"display": "inline"}, 8
                return res
            if step == 8 and str(tumor).lower() not in ["brca", "brca_pam50", "breast"]:
                res[23], res[24], res[25], res[26], res[30] = {"display": "none"}, {"display": "none"}, {"display": "none"}, {"display": "inline"}, 9
                return res

            # TMP is OPTIONAL for "divided" tumors (its integrative scheme does not match the
            # centroid subtypes). Skip it unless the user opted in via run_tmp_tick.
            run_tmp_on = bool(run_tmp and 1 in run_tmp)
            if step == 5 and str(tumor).lower() in DIVIDED_TUMORS and not run_tmp_on:
                res[12], res[13], res[14], res[35], res[30] = {"display": "none"}, {"display": "none"}, {"display": "none"}, {"display": "inline"}, 6
                return res

            if step == 5:
                norm_file = os.path.join(out_dir, "norm_data.csv")
                counts_file = os.path.join(out_dir, "counts.csv")
                if not os.path.exists(norm_file) and not os.path.exists(counts_file):
                    res[12], res[14], res[35] = {"display": "none"}, {"display": "inline"}, {"display": "none"}
                    res[30], res[32] = 0, False
                    res[31] = dbc.Badge(
                        "Error in tmp: missing counts.csv / norm_data.csv. Re-upload counts and rerun.",
                        color="danger"
                    )
                    current_process["proc"] = None
                    current_process["cmd"] = None
                    return res

            # Rscript's own front-end re-encodes spaces in an *absolute* --file=
            # path as the literal string "~+~" before R ever sees it (e.g.
            # ".../Application Support/..." becomes ".../Application~+~Support/...").
            # That corrupts every path annotator.R/merge.R derive from their own
            # script location (project_root, the centroid/utilities lookups, the
            # TMP JSON path, ...) whenever the app is installed under a path with
            # a space in it - the default macOS per-user install location. A
            # *relative* script path doesn't trigger this: Rscript resolves it
            # via the process's cwd, which Popen inherits correctly (confirmed
            # above to be PROJECT_ROOT) without re-encoding anything. Both
            # annotator.R and merge.R already assume cwd == PROJECT_ROOT for
            # their own internal relative paths (source("scripts/..."), "utilities/..."),
            # so cwd is intentionally left unset here rather than pointed at
            # SCRIPT_DIR.
            script_rel = os.path.join("scripts", "merge.R" if step == 9 else "annotator.R")
            if step == 9:
                # Final merge: equal-vote consensus; "1" = user opted in to the validated
                # weighting (merge.R applies it only for LUAD/LUSC/PDAC/BRCA, else equal vote).
                weighting_on = bool(weighting and 1 in weighting) and str(tumor).lower() in WEIGHTING_TUMORS
                cmd = ["Rscript", script_rel, out_dir, str(tumor), "1" if weighting_on else "0"]
            else:
                counts_dir = out_dir
                cmd = ["Rscript", script_rel, out_dir, counts_dir, str(tumor), method_name]

            # Timing/CPU baseline for this step, read back on completion
            # below - see _write_run_report.
            current_process["step_start"] = time.time()
            current_process["rusage_before"] = resource.getrusage(resource.RUSAGE_CHILDREN)

            current_process["proc"] = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True
            )
            current_process["step"] = step
            current_process["cmd"] = cmd
            res[idx] = {"display": "inline-block"}
            if step == 5:
                res[35] = {"display": "none"}
            res[31] = dbc.Badge(f"Phase: {method_name}...", color="warning")
            res[33] = True if step >= 1 else dash.no_update
            return res

        poll = current_process["proc"].poll()
        if poll is None: return res 

        if poll == 0:
            _, err = current_process["proc"].communicate()
            res[idx], res[idx+1] = {"display": "none"}, {"display": "inline"}

            # Per-step timing/CPU for run_report.txt/.json - see
            # _write_run_report. Wall time from this step's own start;
            # CPU time from the RUSAGE_CHILDREN delta (maxrss isn't
            # diffable per-step the same way, see the report's own note).
            rusage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
            rusage_before = current_process.get("rusage_before")
            cpu_time = None
            if rusage_before is not None:
                cpu_time = ((rusage_after.ru_utime + rusage_after.ru_stime)
                            - (rusage_before.ru_utime + rusage_before.ru_stime))
            step_start = current_process.get("step_start")
            current_process["stats"][method_name] = {
                "duration_sec": (time.time() - step_start) if step_start else None,
                "cpu_time_sec": cpu_time,
            }

            if step < 9:
                res[30] = step + 1
            else:
                res[30] = 0
                res[31] = dbc.Badge("All Analysis Completed!", color="success")
                res[32] = False
                res[33] = False # RE-ABILITA Normalize
                res[34] = False # ABILITA IL TASTO RESULTS
                cleanup_temp_uploads()
                cleanup_tmp_runtime()
                _write_run_report(
                    out_dir=get_clean_path(base, folder),
                    tumor=tumor,
                    folder_name=folder,
                    counts_gene_column=counts_gene_column,
                    clinical_sample_column=clinical_sample_column,
                    run_tmp_requested=bool(run_tmp and 1 in run_tmp),
                    step_stats=current_process["stats"],
                    pipeline_start=current_process.get("pipeline_start"),
                )
            current_process["proc"] = None
            current_process["cmd"] = None
            return res
        else:
            _, err = current_process["proc"].communicate()
            res[idx], res[idx+2] = {"display": "none"}, {"display": "inline"}
            res[30], res[32], res[33] = 0, False, False
            # R's own traceback almost always ends with a bare "Execution
            # halted" - that line alone tells the user nothing, so skip it
            # and surface the actual last descriptive line instead (e.g.
            # the cli::cli_abort() message GSVA/etc. print above it).
            err_lines = [l for l in (err or "").strip().splitlines() if l.strip()]
            useful_lines = [l for l in err_lines if l.strip() != "Execution halted"]
            err_msg = (useful_lines or err_lines or ["No stderr captured"])[-1]
            res[31] = dbc.Badge(f"Error in {method_name}: {err_msg.strip()[:120]}", color="danger")

            # Persist the FULL stderr (not just the 120-char badge snippet)
            # so it's inspectable from the GUI via "View Error Details",
            # and it survives on disk for later (page reload, container
            # restart) even though the button itself resets on the next run.
            full_text = (err or "No stderr captured").strip()
            out_dir = get_clean_path(base, folder)
            log_path = os.path.join(out_dir, "logs", f"{method_name}_error.log")
            try:
                os.makedirs(os.path.dirname(log_path), exist_ok=True)
                with open(log_path, "w") as f:
                    f.write(f"Step: {method_name}\nCommand: {' '.join(current_process['cmd'] or [])}\n\n{full_text}")
            except OSError:
                pass
            res[36] = {"display": "inline-block"}
            res[37] = {"method": method_name, "path": log_path, "text": full_text}

            cleanup_tmp_runtime()
            current_process["proc"] = None
            current_process["cmd"] = None
            return res
