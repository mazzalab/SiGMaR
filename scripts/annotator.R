args <- commandArgs(trailingOnly=TRUE)
output_fold     <- args[1]
temp_input_dir  <- args[2]
tumor_type      <- args[3]
method_to_run   <- args[4]

options(warn = -1)

library(readr)
library(dplyr)
library(tidyr)

source(file.path("scripts", "R_functions.R"))
log_path <- file.path(output_fold, "TMP", "tmp_run.log")
dir.create(file.path(output_fold, "TMP"), recursive = TRUE, showWarnings = FALSE)
log_line <- function(...) {
  msg <- paste0(..., collapse = "")
  cat(msg, "\n", file = log_path, append = TRUE)
}

log_line("=== annotator.R start: method=", method_to_run, " tumor=", tumor_type, " ===")

#check data
norm_file <- file.path(output_fold, "norm_data.csv")
load_file  <- file.path(temp_input_dir, "counts.csv")
output_counts_file <- file.path(output_fold, "counts.csv")

if (file.exists(norm_file)) {
    message("### Phase 3: Rilevato file NORMALIZZATO dalla Phase 2. Utilizzo questo. ###")
    log_line("Using normalized file: ", norm_file)
    input_path <- norm_file
} else if (file.exists(load_file)) {
    message("### Phase 3: File normalizzato non trovato. Utilizzo il file da upload. ###")
    log_line("Using raw upload file: ", load_file)
    input_path <- load_file
} else if (file.exists(output_counts_file)) {
    message("### Phase 3: File normalizzato non trovato. Utilizzo counts.csv dalla cartella output. ###")
    log_line("Using output counts file: ", output_counts_file)
    input_path <- output_counts_file
} else {
    log_line("ERROR: neither norm_file, temp load_file nor output_counts_file exists")
    stop("Errore critico: Nessun file di conte (norm o raw) trovato!")
}

# load
df <- as.data.frame(read_delim(input_path, delim=NULL))
.gene_ids <- make.names(df[[1]], unique = TRUE)
df <- df[ , sapply(df, is.numeric), drop = FALSE]   # drop = FALSE: a single-sample upload must stay a 1-column data.frame
rownames(df) <- .gene_ids

centroid_path <- file.path("utilities", "centroids", paste0(tumor_type, ".txt"))

# --- Fixed-reference standardisation statistics (see R_functions.R). When the
#     tumour ships utilities/reference_stats/<tumor>_genes.tsv / _ssgsea.tsv,
#     centroid correlation, ssGSEA and NTP standardise each sample against the
#     TCGA reference cohort instead of against the other uploaded samples.
#     Optional 5th argument (or env SIGMAR_STANDARDIZE): "reference" (default)
#     or "cohort" = standardise within the uploaded cohort instead (for data on
#     a different scale/platform than the TCGA reference, e.g. FPKM/microarray,
#     when the cohort is large and subtype-mixed).
standardize_mode <- tolower(if (length(args) >= 5 && nzchar(args[5])) args[5] else Sys.getenv("SIGMAR_STANDARDIZE", "reference"))
if (standardize_mode == "cohort") {
  ref_genes <- NULL; ref_sets <- NULL
  log_line("standardisation mode: cohort (reference statistics ignored by request)")
} else {
  ref_genes <- load_reference_stats(tumor_type, "genes")
  ref_sets  <- load_reference_stats(tumor_type, "ssgsea")
}
log_line("reference standardisation: genes=", if (is.null(ref_genes)) "none (within-cohort)" else nrow(ref_genes),
         " ssgsea_sets=", if (is.null(ref_sets)) "none (within-cohort)" else nrow(ref_sets))

# NTP calls whose BH-FDR exceeds this cut-off are reported but do not vote in the
# consensus (canonical NTP / CMScaller behaviour: non-significant = unclassified).
NTP_FDR_CUTOFF <- 0.05

# --- Input scale, decided once. norm_data.csv (normalize.R) is DESeq2
#     size-factor normalized counts on the LINEAR scale; a user may instead
#     upload an already log-scale matrix (VST, log2-TPM, ...). Each method
#     receives the scale it was designed/validated for:
#       log2(x+1)  -> centroid correlation, ssGSEA, NTP, BreastSubtypeR,
#                     consensusOV, CMSclassifier (RF/SSP)
#       linear     -> GDAN-TMP models, CMScaller (which logs internally)
#     The log2 step is skipped when the input already looks log-scale
#     (max value <= 50, the same rule normalize.R uses), so log data is never
#     transformed twice; in that case GDAN-TMP gets the un-logged matrix.
.max_val   <- suppressWarnings(max(as.matrix(df), na.rm = TRUE))
input_is_log <- is.finite(.max_val) && .max_val <= 50
df_log <- if (input_is_log) df else log2(pmax(as.matrix(df), 0) + 1)
df_log <- as.data.frame(df_log); rownames(df_log) <- rownames(df)
# GDAN-TMP quantile-rescales the user matrix onto linear TCGA RSEM reference
# matrices, so a log-scale upload is mapped back to the linear scale (2^x - 1)
# for TMP only; every other method receives df_log / df as documented above.
df_tmp <- if (input_is_log) as.data.frame(pmax(2^as.matrix(df) - 1, 0)) else df
rownames(df_tmp) <- rownames(df)
log_line("input scale: max=", signif(.max_val, 4), " -> ", if (input_is_log) "already log-scale (used as is; un-logged 2^x-1 for GDAN-TMP)" else "linear (log2(x+1) applied for log-scale methods)")

# # 1. NTP
if (method_to_run == "ntp") {
  message("### Esecuzione Metodo 1: NTP ###")
  gct_out = gct_convert(df_log)
  gct_path=gct_out$gct_path

  template <- ntp_template(centroid_path, output_fold)
  template_file=template$out_path
  class_map=template$class_map
  nresmpl = 1000            # standard NTP default (Hoshida 2010 PLoS ONE; CMScaller/Eide 2017 nPerm=1000)
  dist.selection= "cosine"

  # NTP revised: the original NTPez port under-performed badly (see NTP_predict
  # header in R_functions.R). NTP_predict is a correct cosine nearest-template
  # implementation; same output contract (ntp_classification.txt / predict.label),
  # plus a permutation p-value / BH-FDR confidence (nresmpl resamples).
  NTP_predict(
    input.exp.filename = gct_path,
    input.features.filename = template_file,
    output.name = file.path(output_fold, "NTP"),
    dist.selection = dist.selection,
    nresmpl = nresmpl,
    class_map = class_map,
    log_transform = FALSE,          # df_log is already on the log2 scale
    ref = ref_genes
  )
  # Add the voting label: NA when the permutation FDR is not significant.
  ntp_file <- file.path(output_fold, "NTP", "ntp_classification.txt")
  if (file.exists(ntp_file)) {
    ntp_out <- read.delim(ntp_file, stringsAsFactors = FALSE)
    sig <- is.finite(ntp_out$BH.FDR) & ntp_out$BH.FDR <= NTP_FDR_CUTOFF
    ntp_out$predict.label.fdr <- ifelse(sig, ntp_out$predict.label, NA_character_)
    write.table(ntp_out, ntp_file, quote = FALSE, sep = "\t", row.names = FALSE)
    log_line("NTP: ", sum(!sig), " of ", nrow(ntp_out), " calls have BH-FDR > ", NTP_FDR_CUTOFF, " and do not vote")
  }
}

# # 2. ssGSEA
if (method_to_run == "ssgsea") {
  message("### Esecuzione Metodo 2: ssGSEA ###")

  thr_up=0.02
  thr_dn=-0.02
  ssgsea_fun(df_log, centroid_path, output_fold, thr_up, thr_dn, ref_sets = ref_sets, ref_genes = ref_genes)
}

# # 3. Centroid correlation (Pearson Correlation / Cosine Similarity / Euclidean Distance)
if (method_to_run == "centroid") {
  message("### Esecuzione Metodo 3: Centroid correlation ###")

  centroid_corr(df_log, centroid_path, output_fold, ref = ref_genes)
}

# # 4. TMP
if (method_to_run == "tmp") {

  message("### Esecuzione Metodo 4: TMP ###")
  log_line("TMP branch entered")
  #token_file <- normalizePath(file.path(getwd(), "uploads/temp/token/token.csv"), mustWork = TRUE)
  output_tmp <- normalizePath(file.path(output_fold, "TMP"), mustWork = FALSE)
  log_line("output_tmp=", output_tmp)

  json_path_abs <- normalizePath(input_for_tmp(df_tmp, output_fold), mustWork = TRUE)
  json_filename <- basename(json_path_abs)
  extracted_tumor <- gsub("entrez2tmp_|_GEXP\\.json", "", json_filename)
  log_line("json_path_abs=", json_path_abs)
  log_line("json_filename=", json_filename, " extracted_tumor=", extracted_tumor)

  sh_script_abs <- normalizePath("scripts/run_all_models_docker.sh", mustWork = TRUE)
  log_line("shell_script=", sh_script_abs)
  
  #commentato per test
  # shQuote() each path - system2() does NOT quote args on its own, and an
  # install path containing a space (e.g. "~/Library/Application Support/...",
  # the default macOS per-user install location) gets split into separate
  # shell tokens without it, so bash looks for a file literally named
  # ".../Application" and fails with "No such file or directory" (exit 127).
  exit_code <- system2("bash", args = shQuote(c(sh_script_abs, output_tmp, extracted_tumor, json_path_abs)), stdout = log_path, stderr = log_path)
  log_line("TMP exit_code=", exit_code)
  if (!identical(exit_code, 0L)) {
    log_line("TMP FAILED with exit code ", exit_code)
    stop(paste("TMP pipeline failed with exit code", exit_code))
  }
  log_line("TMP completed successfully")
  }

# # 5. Consensus Ovary
if (method_to_run == "cons_ov" && tolower(tumor_type) %in% c("ov", "ovary")) {
  message("### Esecuzione Metodo 4: Consensus Ovary ###")
  log_line("Consensus OV branch entered")
  consensus_ov_eval(df_log, output_fold)
}

# # 6. CMS
if (method_to_run == "cms" && tolower(tumor_type) %in% c("coad", "coadread", "read")) {
  message("### Esecuzione Metodo 5: CMS ###")
  log_line("CMS branch entered")
  cms(df_log, output_fold, df_linear = df, rnaseq_counts = !input_is_log)
}

# # 7. BreastSubtypeR (BRCA only)
if (method_to_run == "breast_subtype" && tolower(tumor_type) %in% c("brca", "brca_pam50", "breast")) {
  message("### Esecuzione Metodo 7: Breast subtype ###")
  log_line("Breast subtype branch entered")
  breast_subtype(df_log, output_fold)
}

log_line("=== annotator.R end ===")
