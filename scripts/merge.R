args <- commandArgs(trailingOnly=TRUE)
output_fold <- args[1]
tumor_type <- args[2]

library(readr)
library(dplyr)
library(tidyr)
library(purrr)
library(jsonlite)

dir.create(output_fold, recursive = TRUE, showWarnings = FALSE)
dir.create(file.path(output_fold, "TMP"), recursive = TRUE, showWarnings = FALSE)

# --- FUNZIONI DI SUPPORTO ---

safe_read <- function(path, type = "delim", col_names = TRUE) {
  if (!file.exists(path)) {
    message(paste("!!! Attenzione: File non trovato ->", path))
    return(NULL)
  }
  tryCatch({
    if (type == "delim") return(read_delim(path, col_names = col_names, show_col_types = FALSE))
    if (type == "csv")   return(read_csv(path, show_col_types = FALSE))
  }, error = function(e) {
    message(paste("!!! Errore nella lettura del file:", path))
    return(NULL)
  })
}

safe_format <- function(df, name_tag = "") {
  if (is.null(df)) return(NULL)
  tryCatch({
    df <- as.data.frame(df)
    names(df)[1] <- "Samples" 
    bad_samples <- c("", "NA", "Entrez_Gene_Id", "Hugo_Symbol", "Gene")
    df <- df[!is.na(df$Samples) & !(df$Samples %in% bad_samples), ]
    return(df)
  }, error = function(e) {
    message(paste("!!! Errore formattazione:", name_tag))
    return(NULL)
  })
}

# --- 0. CARICAMENTO TABELLA DI MAPPING ---
# Preferiamo il mapping completo, ma se non c'è degradiamo sulla tabella TMP
# già presente nel repo e, in ultima istanza, lasciamo i valori originali.
mapping_file <- "sigmar_keys.tsv" 

if (!file.exists(mapping_file)) {
  stop("File sigmar_keys.tsv non trovato.")
}

# Carichiamo il TSV
sigmar_master <- read_tsv(mapping_file, show_col_types = FALSE)

# Filtriamo per il tumore corrente (passato tramite args[2])
sigmar_mapping <- sigmar_master %>%
  filter(Tumour == tumor_type)

# Funzione universale di conversione in Name_Sigmar
convertToSigmar <- function(value, type = "TMP") {
  if (is.na(value) || value == "/" || value == "" || value == "NA") {
    return(value)
  }

  normalize_label <- function(x) {
    parts <- trimws(unlist(strsplit(as.character(x), "[;,]")))
    parts <- parts[parts != ""]
    if (length(parts) == 0) {
      return("")
    }
    paste(sort(parts), collapse = ",")
  }
  
  match_row <- switch(type,
    "TMP" = {
      sigmar_mapping %>% filter(TMP_Output == value)
    },
    "CONSENSUS_OV" = {
      sigmar_mapping %>% filter(Consensus_OV == value)
    },
    "CMS" = {
      target <- normalize_label(value)
      sigmar_mapping %>%
        rowwise() %>%
        filter(normalize_label(CMS) == target) %>%
        ungroup()
    },
    "OTHER" = {
      # Logica per NON_TMP1: gestisce i valori multipli separati da ";"
      sigmar_mapping %>% 
        rowwise() %>%
        filter(any(trimws(unlist(strsplit(as.character(NON_TMP1), "[;,]"))) == value)) %>%
        ungroup()
    },
    sigmar_mapping %>% filter(TMP_Output == value)
  ) %>% slice(1)
  
  if (nrow(match_row) > 0) {
    return(match_row$Name_Sigmar)
  } else {
    return(value)
  }
}

# Funzione helper per applicare il mapping
apply_sigmar_mapping <- function(df, col_name, method_type) {
  if (is.null(df)) return(NULL)
  df[[col_name]] <- sapply(df[[col_name]], convertToSigmar, type = method_type)
  return(df)
}

# --- 1. CARICAMENTO DATI ---
aklimate    <- safe_read(file.path(output_fold,"TMP","aklimate_preds.tsv")) %>% safe_format("aklimate")
cloudforest <- safe_read(file.path(output_fold,"TMP","cloudforest_preds.tsv"), col_names = F) %>% safe_format("cloudforest")
jadbio      <- safe_read(file.path(output_fold,"TMP","jadbio_preds.csv"), type = "csv") %>% safe_format("jadbio")
skgrid      <- safe_read(file.path(output_fold,"TMP","skgrid_preds.tsv")) %>% safe_format("skgrid")
subscope    <- safe_read(file.path(output_fold,"TMP","subscope_results.txt")) %>% safe_format("subscope")

# --- 2. UNIFORM_TMP ---
if(!is.null(jadbio)) {
  jadbio <- jadbio %>%
    rowwise() %>%
    mutate(result_jadbio = names(across(-Samples))[which.max(c_across(-Samples))]) %>%
    ungroup() %>%
    mutate(result_jadbio = gsub(".*= (.*) )", "\\1", result_jadbio),
           result_jadbio = gsub(":", "_", result_jadbio)) %>%
    dplyr::select(Samples, result_jadbio)
  jadbio <- apply_sigmar_mapping(jadbio, "result_jadbio", "TMP")
}

if(!is.null(aklimate)) {
  aklimate <- aklimate %>% dplyr::select(Samples, result_aklimate = 2)
  # Conversione in Cluster_name
  aklimate <- apply_sigmar_mapping(aklimate, "result_aklimate", "TMP")
}

if(!is.null(cloudforest)) {
  cloudforest <- cloudforest %>% dplyr::select(Samples, result_cloudforest = 2)
  # Conversione in Cluster_name
  cloudforest <- apply_sigmar_mapping(cloudforest, "result_cloudforest", "TMP")
}

if(!is.null(skgrid)) {
  skgrid <- skgrid %>% dplyr::select(Samples, result_skgrid = 2)
  # Conversione in Cluster_name
  skgrid <- apply_sigmar_mapping(skgrid, "result_skgrid", "TMP")
}

if(!is.null(subscope)) {
  subscope <- subscope %>% 
    dplyr::select(Samples, result_subscope = 2) %>%
    mutate(result_subscope = gsub("\\|.*$", "", result_subscope))
  # Conversione in Cluster_name
  subscope <- apply_sigmar_mapping(subscope, "result_subscope", "TMP")
}

# --- 3. MERGE TMP ---
all_tmp <- list(aklimate, cloudforest, jadbio, skgrid, subscope) %>% 
  keep(~ !is.null(.x)) %>% 
  {
    if (length(.) == 0) {
      tibble::tibble(Samples = character())
    } else if (length(.) == 1) {
      .[[1]]
    } else {
      reduce(., left_join, by = "Samples")
    }
  }

# --- 4. ALTRI METODI ---

# CONSENSUS_OV
consensus <- safe_read(file.path(output_fold,"Consensus_OV","consensusOV_probabilities.csv"), type = "csv") %>% safe_format("consensusOV")
if(!is.null(consensus)) {
  idx <- max.col(consensus %>% dplyr::select(-Samples), ties.method = "first")
  col_names <- names(consensus %>% dplyr::select(-Samples))
  consensus <- consensus %>%
    mutate(consensus_ov_pred = col_names[idx]) %>%
    mutate(consensus_ov_pred = gsub("_.*$", "", consensus_ov_pred)) %>%
    dplyr::select(Samples, consensus_ov_pred)
    consensus <- apply_sigmar_mapping(consensus, "consensus_ov_pred", "CONSENSUS_OV")
}

# CMS (COAD only)
cms <- safe_read(file.path(output_fold,"CMS","cms_classification.csv"), type = "csv") %>% safe_format("CMS")
if(!is.null(cms)) {
  cms <- cms %>%
    dplyr::select(
      Samples,
      cms_rf_pred = RF_subtype,
      cms_ssp_pred = SSP_subtype,
      cms_caller_pred = CMScaller_subtype
    )
  cms <- apply_sigmar_mapping(cms, "cms_rf_pred", "CMS")
  cms <- apply_sigmar_mapping(cms, "cms_ssp_pred", "CMS")
  cms <- apply_sigmar_mapping(cms, "cms_caller_pred", "CMS")
}

# Centroid Correlation
pce <- safe_read(file.path(output_fold,"Centroid_Correlation","centroid_corr_classification.txt")) %>% safe_format("Centroid_Correlation")
if(!is.null(pce)) {
  pce <- pce %>%
    mutate(Samples = Sample) %>% 
    dplyr::select(Samples, 
                  pce_pearson = `Assigned Subtype Pearson`, 
                  pce_cosine = `Assigned Subtype Cosine`, 
                  pce_euclidean = `Assigned Subtype Euclidean`)
    pce <- apply_sigmar_mapping(pce, "pce_pearson", "OTHER")
    pce <- apply_sigmar_mapping(pce, "pce_cosine", "OTHER")
    pce <- apply_sigmar_mapping(pce, "pce_euclidean", "OTHER")
}

# GSEA
gsea <- safe_read(file.path(output_fold,"ssGSEA","ssgsea_classification.txt")) %>% safe_format("GSEA")
if(!is.null(gsea)) {
  gsea <- gsea %>% dplyr::select(Samples, ss_gsea_pred = predicted_cluster)
  gsea <- apply_sigmar_mapping(gsea, "ss_gsea_pred", "OTHER")
}

# NTP
ntp <- safe_read(file.path(output_fold,"NTP","ntp_classification.txt")) %>% safe_format("NTP")
if(!is.null(ntp)) {
  # predict.label.fdr (annotator.R) is NA when the permutation FDR is not
  # significant: such calls are shown in the NTP output but do not vote.
  if ("predict.label.fdr" %in% names(ntp)) {
    ntp <- ntp %>% dplyr::select(Samples, ntp_pred = predict.label.fdr)
  } else {
    ntp <- ntp %>% dplyr::select(Samples, ntp_pred = predict.label)
  }
  ntp <- apply_sigmar_mapping(ntp, "ntp_pred", "OTHER")
}

# BreastSubtypeR (BRCA only)
breast <- safe_read(file.path(output_fold,"breast_subtype","breast_subtypes.csv"), type = "csv") %>% safe_format("BreastSubtypeR")
if(!is.null(breast)) {
  breast <- breast %>%
    dplyr::select(
      Samples,
      breast_aims_pred = AIMS,
      breast_sspbc_pred = sspbc
    )
  breast <- apply_sigmar_mapping(breast, "breast_aims_pred", "OTHER")
  breast <- apply_sigmar_mapping(breast, "breast_sspbc_pred", "OTHER")
}

# --- 5. MERGE FINALE ---

# Usiamo una lista robusta per evitare errori se alcuni oggetti sono NULL
final_pieces <- list(all_tmp, consensus, cms, pce, gsea, ntp, breast) %>%
  # drop NULL pieces AND empty (0-row) ones — e.g. all_tmp when TMP was skipped,
  # otherwise the empty tibble becomes the left_join base and drops every sample.
  keep(~ !is.null(.x) && nrow(.x) > 0)

all_final <- if (length(final_pieces) == 0) {
  tibble::tibble(Samples = character())
} else if (length(final_pieces) == 1) {
  final_pieces[[1]]
} else {
  final_pieces %>% reduce(left_join, by = "Samples")
}

all_final <- all_final %>%
  filter(!Samples %in% c("Entrez_Gene_Id", "Hugo_Symbol", "Gene"))

# Salvataggio
write.table(all_final, file.path(output_fold, "final_complete_summary.txt"), sep = "\t", row.names = F, quote = F)

# --- 6. GENERAZIONE REPORT CON CONSENSUS DINAMICO ---

# Method groups by output taxonomy.
#   TMP methods    -> GDAN-TMP subtype names (cluster-derived).
#   non-TMP methods-> centroid / ssGSEA / NTP / tumor-specific tool names.
tmp_native_cols <- c("result_aklimate", "result_jadbio", "result_skgrid",
                     "result_subscope", "result_cloudforest")
non_tmp_cols    <- c("cms_rf_pred", "cms_ssp_pred", "cms_caller_pred", "consensus_ov_pred",
                     "pce_pearson", "pce_cosine", "pce_euclidean",
                     "ss_gsea_pred", "ntp_pred", "breast_aims_pred", "breast_sspbc_pred")
pred_cols <- c(tmp_native_cols, non_tmp_cols)

# "Divided" tumors: the TMP taxonomy differs from the centroid/tool taxonomy
# (per sigmar_keys.tsv), so we report TWO independent consensus axes:
#   primary_subtype   = consensus of the non-TMP methods (named/interpretable)
#   secondary_subtype = consensus of the TMP methods (GDAN-TMP integrative)
# "Merged" tumors keep a single consensus over all methods (secondary = NA).
# BRCA is MERGED: the GDAN-TMP BRCA models predict the same PAM50 taxonomy as the
# centroid methods, so all 12 methods vote on one axis. Because those models were
# trained on TCGA-BRCA, BRCA's validation and its weighting are fitted on the
# external SCAN-B cohort (GEO GSE96058), where every method is out-of-sample.
divided_tumors <- c("coad", "coadread", "read", "gbm", "luad", "lusc", "meso", "pdac", "hnsc", "hnscc")
is_divided <- tolower(as.character(tumor_type)) %in% divided_tumors
# TMP is optional for divided tumors; if no TMP columns are present the run is single-axis.
has_tmp <- any(tmp_native_cols %in% names(all_final))

# --- Consensus (default): one equal vote per method (majority). Non-calls
#     ("Unknown" from CMSclassifier/CMScaller, "Uncertain" from ssGSEA, NA/empty,
#     NTP calls with non-significant FDR) do not vote. A sample is "Uncertain"
#     when no method votes, when every vote is distinct, or when the top two
#     classes tie; confidence = share of the votes carried by the winning class
#     (for an Uncertain sample: the share of the largest class). The optional
#     validated weighting (below) replaces this rule for the Tier-1 tumours. ---
.non_votes <- c("", "NA", "N/A", "Uncertain", "Unknown", "unknown", "uncertain")
.consensus <- function(df, cols) {
  cols <- intersect(cols, names(df)); n <- nrow(df)
  call <- rep("Uncertain", n); conf <- rep(0, n)
  if (length(cols) == 0) return(list(call = call, conf = conf))
  M <- as.matrix(df[, cols, drop = FALSE])
  for (i in seq_len(n)) {
    vals <- as.character(M[i, ])
    ok <- !is.na(vals) & !(vals %in% .non_votes)
    v <- vals[ok]
    if (length(v) == 0) next
    agg <- sort(table(v), decreasing = TRUE)
    conf[i] <- as.numeric(agg[1] / length(v))
    if (length(agg) > 1 && agg[2] == agg[1]) next               # tie -> Uncertain
    if (length(v) > 1 && length(agg) == length(v)) next           # total disagreement -> Uncertain
    call[i] <- names(agg)[1]
  }
  list(call = call, conf = conf)
}

# --- OPTIONAL validated weighting (args[3] = "1"): Dawid-Skene (1979) per-method
#     confusion-matrix weighting, fitted on the full TCGA cohort and validated by
#     repeated balanced hold-out ONLY for tumors whose validation set is not
#     circular with the centroid (Tier-1: centroids defined off TCGA -> LUAD,
#     LUSC, PDAC, BRCA). utilities/consensus_scheme.tsv lists those tumors with
#     "ds", or "equal" (no validated gain -> equal vote). Any tumor absent from
#     the file, or any missing artifact, silently means: equal vote. The primary
#     axis only is affected; the TMP secondary axis is always the equal vote.
#     (A per-class NNLS weighting scheme was tried and retired in the 2026-09-17
#     pipeline audit in favor of Dawid-Skene across the board.)
weighting_on <- length(args) >= 3 && tolower(trimws(args[3])) %in% c("1", "true", "yes", "on", "weighted")
.norm_tumor <- function(t) {
  t <- tolower(trimws(as.character(t)))
  if (t %in% c("brca", "brca_pam50", "breast")) return("brca")
  if (t %in% c("bladder", "blca"))             return("blca")
  if (t %in% c("coad", "coadread", "read"))     return("coad")
  if (t %in% c("hnsc", "hnscc"))               return("hnsc")
  if (t %in% c("pdac", "paad"))                return("pdac")
  t
}
.norm_lab <- function(x) {
  x <- tolower(trimws(as.character(x)))
  x <- gsub("_like", "", x); x <- gsub("[^a-z0-9]", "", x)
  x[x == "classic"] <- "classical"
  x
}
.tkey <- .norm_tumor(tumor_type)
.read_tsv_safe <- function(f) if (file.exists(f)) tryCatch(read.delim(f, stringsAsFactors = FALSE), error = function(e) NULL) else NULL
consensus_mode <- "equal"
.cls_disp <- NULL
if (weighting_on) {
  st <- .read_tsv_safe(file.path("utilities", "consensus_scheme.tsv"))
  sch <- if (!is.null(st) && all(c("Tumour", "Scheme") %in% names(st))) tolower(st$Scheme[tolower(st$Tumour) == .tkey]) else character(0)
  ct <- .read_tsv_safe(file.path("utilities", "consensus_classes.tsv"))
  if (!is.null(ct)) { ct <- ct[tolower(ct$Tumour) == .tkey, , drop = FALSE]; if (nrow(ct) > 0) .cls_disp <- setNames(ct$Display, ct$Token) }
  .DS <- NULL
  if (length(sch) == 1 && sch == "ds" && !is.null(.cls_disp)) {
    # Dawid-Skene (1979): per-method confusion matrices P(called | true), Laplace-smoothed,
    # fitted on the full TCGA cohort (utilities/method_confusion.tsv); naive-Bayes aggregation.
    cm <- .read_tsv_safe(file.path("utilities", "method_confusion.tsv"))
    if (!is.null(cm)) {
      cm <- cm[tolower(cm$Tumour) == .tkey, , drop = FALSE]
      toks <- names(.cls_disp); pri <- cm[cm$Method == "__prior__", , drop = FALSE]
      if (nrow(pri) > 0) {
        .DS <- list(lp0 = log(setNames(pri$P, pri$True)[toks]), th = list())
        for (m in unique(cm$Method[cm$Method != "__prior__"])) {
          sub <- cm[cm$Method == m, , drop = FALSE]
          mat <- matrix(1e-6, length(toks), length(toks), dimnames = list(toks, toks))
          for (r in seq_len(nrow(sub))) if (sub$True[r] %in% toks && sub$Called[r] %in% toks) mat[sub$True[r], sub$Called[r]] <- sub$P[r]
          .DS$th[[m]] <- log(mat)
        }
        consensus_mode <- "ds"
      }
    }
  }
  if (consensus_mode == "ds") {
    message("Weighted consensus ON for ", .tkey, ": validated Dawid-Skene confusion matrices (", length(.DS$th), " methods).")
  } else if (length(sch) == 1 && sch == "equal") {
    message("Weighted consensus requested for ", .tkey, ": no validated gain over the equal vote for this tumor -> equal vote used.")
  } else {
    message("Weighted consensus requested for ", .tkey, ": weighting is only validated for LUAD/LUSC/PDAC/BRCA -> equal vote used.")
  }
}

# Dawid-Skene consensus: posterior over classes = prior x prod_m P(call_m | class); argmax;
# confidence = posterior of the winner.
.consensus_ds <- function(df, cols) {
  cols <- intersect(cols, names(df)); n <- nrow(df)
  call <- rep("Uncertain", n); conf <- rep(0, n)
  toks <- names(.cls_disp); M <- as.matrix(df[, cols, drop = FALSE])
  for (i in seq_len(n)) {
    lp <- .DS$lp0; voted <- FALSE
    for (m in cols) {
      p <- M[i, m]
      if (is.na(p) || p %in% .non_votes || is.null(.DS$th[[m]])) next
      tk <- .norm_lab(p)
      if (tk %in% toks) { lp <- lp + .DS$th[[m]][, tk]; voted <- TRUE }
    }
    if (!voted) next
    lp <- lp - max(lp); pp <- exp(lp) / sum(exp(lp))
    call[i] <- .cls_disp[[names(which.max(pp))]]; conf[i] <- max(pp)
  }
  list(call = call, conf = conf)
}

# Primary axis: divided -> non-TMP methods; merged -> all methods.
# Secondary axis (divided tumors, TMP run): the TMP methods, always equal vote.
.af_chr   <- all_final %>% mutate(across(any_of(pred_cols), as.character))
.prim_cols <- if (is_divided) non_tmp_cols else pred_cols
.prim     <- if (consensus_mode == "ds") .consensus_ds(.af_chr, .prim_cols) else .consensus(.af_chr, .prim_cols)
.sec      <- if (is_divided && has_tmp) .consensus(.af_chr, tmp_native_cols) else NULL

dashboard_json <- all_final %>%
  mutate(across(any_of(pred_cols), as.character)) %>%
  mutate(
    # --- primary axis: equal-vote consensus ---
    primary_subtype      = .prim$call,
    confidence           = .prim$conf,
    # --- secondary axis: divided AND TMP was run -> TMP consensus; otherwise NA ---
    secondary_subtype    = if (is_divided && has_tmp) .sec$call else NA_character_,
    secondary_confidence = if (is_divided && has_tmp) .sec$conf else NA_real_
  ) %>%
  rowwise() %>%
  mutate(
    # --- per-method details for Dash ---
    details = list(list(
      ntp = if("ntp_pred" %in% names(.)) ntp_pred else "N/A",
      gsea = if("ss_gsea_pred" %in% names(.)) ss_gsea_pred else "N/A",
      consensus = if("consensus_ov_pred" %in% names(.)) consensus_ov_pred else "N/A",
      pce_pearson = if("pce_pearson" %in% names(.)) pce_pearson else "N/A",
      breast_aims = if("breast_aims_pred" %in% names(.)) breast_aims_pred else "N/A",
      breast_sspbc = if("breast_sspbc_pred" %in% names(.)) breast_sspbc_pred else "N/A",
      tmp_summary = if("result_jadbio" %in% names(.)) result_jadbio else "N/A"
    ))
  ) %>%
  ungroup()

# Esportazione finale
write_json(dashboard_json, file.path(output_fold, "dashboard_data.json"), pretty = TRUE)

# Re-write the flat summary WITH the consensus + agreement columns (the earlier
# write happened before consensus was computed). Drops the nested `details` list
# column, which cannot be represented in a TSV. Columns added:
#   primary_subtype / confidence            = consensus + agreement of the
#                                             non-TMP methods (divided tumors)
#                                             or all methods (merged tumors)
#   secondary_subtype / secondary_confidence= consensus + agreement of the TMP
#                                             methods (divided tumors; NA if merged)
summary_out <- dashboard_json %>% dplyr::select(-dplyr::any_of("details"))
# When there is no secondary axis (single-axis run: TMP not run, or a merged tumor),
# secondary_subtype is entirely NA -> drop the two secondary columns from the summary.
if (!("secondary_subtype" %in% names(summary_out)) ||
    all(is.na(summary_out$secondary_subtype))) {
  summary_out <- summary_out %>%
    dplyr::select(-dplyr::any_of(c("secondary_subtype", "secondary_confidence")))
}
write.table(summary_out,
            file.path(output_fold, "final_complete_summary.txt"),
            sep = "\t", row.names = FALSE, quote = FALSE)

# Salviamo anche una copia HTML del report nel run folder - autosufficiente
# (nessun asset esterno) cosi' resta apribile con un doppio click, in linea
# con lo stile gia' usato per gli altri report standalone del progetto.
tumor_type_label <- switch(
  tolower(as.character(tumor_type)),
  "bladder" = "BLCA",
  "blca" = "BLCA",
  "brca_pam50" = "BRCA",
  "brca" = "BRCA",
  "coad" = "COAD",
  "gbm" = "GBM",
  "hnscc" = "HNSCC",
  "luad" = "LUAD",
  "lusc" = "LUSC",
  "meso" = "MESO",
  "ov" = "OV",
  "pdac" = "PDAC",
  "sarc" = "SARC",
  toupper(as.character(tumor_type))
)

.html_escape <- function(x) {
  x <- as.character(x)
  x <- gsub("&", "&amp;", x, fixed = TRUE)
  x <- gsub("<", "&lt;", x, fixed = TRUE)
  x <- gsub(">", "&gt;", x, fixed = TRUE)
  x
}

.fmt_pct <- function(x) {
  x <- suppressWarnings(as.numeric(x))
  ifelse(is.na(x), "-", paste0(round(x * 100), "%"))
}

.fmt_cell <- function(x) {
  x <- as.character(x)
  ifelse(is.na(x) | x == "" | x == "NA", "-", .html_escape(x))
}

# Subtype distribution - how many samples landed in each primary_subtype.
subtype_counts <- summary_out %>%
  dplyr::filter(!is.na(primary_subtype) & primary_subtype != "") %>%
  dplyr::count(primary_subtype, name = "n", sort = TRUE)

distribution_rows <- if (nrow(subtype_counts) == 0) {
  "<tr><td colspan='3'>No consensus subtype available.</td></tr>"
} else {
  paste0(
    "<tr><td>", .html_escape(subtype_counts$primary_subtype), "</td><td>", subtype_counts$n,
    "</td><td>", round(100 * subtype_counts$n / sum(subtype_counts$n)), "%</td></tr>",
    collapse = "\n"
  )
}

# Per-method columns actually present in this run (varies by tumor type and
# which methods were run/skipped - see pred_cols above).
present_pred_cols <- intersect(pred_cols, names(summary_out))
has_secondary <- "secondary_subtype" %in% names(summary_out) &&
  !all(is.na(summary_out$secondary_subtype))

table_header <- paste0(
  "<th>Sample</th>",
  paste0("<th>", .html_escape(present_pred_cols), "</th>", collapse = ""),
  "<th>Primary subtype</th><th>Confidence</th>",
  if (has_secondary) "<th>Secondary subtype</th><th>Secondary confidence</th>" else ""
)

results_rows <- apply(summary_out, 1, function(row) {
  method_cells <- paste0("<td>", vapply(row[present_pred_cols], .fmt_cell, character(1)), "</td>", collapse = "")
  paste0(
    "<tr><td>", .fmt_cell(row[["Samples"]]), "</td>", method_cells,
    "<td><strong>", .fmt_cell(row[["primary_subtype"]]), "</strong></td>",
    "<td>", .fmt_pct(row[["confidence"]]), "</td>",
    if (has_secondary) paste0(
      "<td>", .fmt_cell(row[["secondary_subtype"]]), "</td>",
      "<td>", .fmt_pct(row[["secondary_confidence"]]), "</td>"
    ) else "",
    "</tr>"
  )
})
results_rows <- paste(results_rows, collapse = "\n")

report_html <- paste0(
  "<!doctype html>\n",
  "<html lang='en'>\n",
  "<head>\n",
  "  <meta charset='utf-8'>\n",
  "  <title>Subtyping Report</title>\n",
  "  <style>\n",
  "    body { font-family: Arial, sans-serif; padding: 32px; color: #0f172a; }\n",
  "    h1 { margin-bottom: 4px; }\n",
  "    h2 { margin-top: 32px; font-size: 18px; }\n",
  "    .meta { margin: 0 0 4px 0; color: #475569; }\n",
  "    table { border-collapse: collapse; margin-top: 12px; width: 100%; font-size: 13px; }\n",
  "    th, td { border: 1px solid #cbd5e1; padding: 6px 10px; text-align: left; white-space: nowrap; }\n",
  "    th { background: #f1f5f9; position: sticky; top: 0; }\n",
  "    tr:nth-child(even) td { background: #f8fafc; }\n",
  "    .table-scroll { overflow-x: auto; max-height: 70vh; overflow-y: auto; border: 1px solid #cbd5e1; }\n",
  "    .table-scroll table { border: none; margin-top: 0; }\n",
  "    .dist-table { max-width: 420px; }\n",
  "  </style>\n",
  "</head>\n",
  "<body>\n",
  "  <h1>Multi-Method Subtyping Report</h1>\n",
  "  <p class='meta'>Tumor type: ", tumor_type_label, "</p>\n",
  "  <p class='meta'>Project: ", .html_escape(basename(output_fold)), "</p>\n",
  "  <p class='meta'>Samples: ", nrow(all_final), "</p>\n",
  "  <p class='meta'>Generated: ", format(Sys.time(), "%Y-%m-%d %H:%M:%S"), "</p>\n",
  "  <h2>Subtype distribution</h2>\n",
  "  <table class='dist-table'>\n",
  "    <thead><tr><th>Subtype</th><th>Samples</th><th>Share</th></tr></thead>\n",
  "    <tbody>\n", distribution_rows, "\n    </tbody>\n",
  "  </table>\n",
  "  <h2>Per-sample results</h2>\n",
  "  <div class='table-scroll'>\n",
  "  <table>\n",
  "    <thead><tr>", table_header, "</tr></thead>\n",
  "    <tbody>\n", results_rows, "\n    </tbody>\n",
  "  </table>\n",
  "  </div>\n",
  "</body>\n",
  "</html>\n"
)
writeLines(report_html, file.path(output_fold, "report.html"))

# Metadati del report per la pagina "Saved Studies"
report_metadata <- list(
  study_name = basename(output_fold),
  tumor_type = tumor_type,
  consensus_mode = consensus_mode,      # "equal", "nnls" or "ds" (validated weighting, opt-in)
  total_pzt = nrow(all_final),
  report_created_at = format(Sys.time(), "%Y-%m-%d %H:%M:%S")
)
write_json(report_metadata, file.path(output_fold, "report_metadata.json"), pretty = TRUE, auto_unbox = TRUE)
