args <- commandArgs(trailingOnly=TRUE)
salmon_file <- args[1]
annotation <- args[2]
batch_bool <- as.logical(args[3])
output_fold <- args[4]
batch_col <- ifelse(length(args) >= 5 && nzchar(args[5]), args[5], "batch")
dir.create(output_fold, recursive = TRUE, showWarnings = FALSE)

suppressPackageStartupMessages(library(readr))

# Read count file
counts <- as.data.frame(read_delim(salmon_file, delim=NULL, show_col_types = FALSE))
rownames(counts) = make.names(counts[[1]],unique = T)
counts <- counts[ , sapply(counts, is.numeric), drop = FALSE]

# Load annotation if exists
if (annotation == ""){
    col_data <- data.frame(dummy = rep("all", ncol(counts)))
    rownames(col_data) <- colnames(counts)
} else {
    col_data <- read.csv(annotation, header=TRUE, check.names=FALSE)
    sample_ids <- as.character(col_data[[1]])
    keep <- !duplicated(sample_ids)
    col_data <- col_data[keep, , drop = FALSE]
    rownames(col_data) <- sample_ids[keep]
    col_data <- col_data[, -1, drop = FALSE]

    common_samples <- intersect(colnames(counts), rownames(col_data))
    if (length(common_samples) == 0) {
        stop("No overlapping sample IDs between counts and clinical annotation.")
    }
    counts <- counts[, common_samples, drop = FALSE]
    col_data <- col_data[common_samples, , drop = FALSE]
}

m <- as.matrix(counts)
storage.mode(m) <- "numeric"

# ---------------------------------------------------------------------------
# 1. Decide what the uploaded matrix is. Same rule annotator.R uses downstream
#    (max <= 50 -> log-scale), so the two scripts can never disagree.
#      log-scale (max <= 50)          : used unchanged (VST, log2-TPM, RMA, log-ratio, z-score)
#      linear with negatives          : small batch-correction artefacts (e.g. TCGA
#                                       PanCanAtlas RSEM) -> clipped to 0, then normalized
#      linear (counts / RSEM / TPM)   : DESeq2 median-of-ratios size factors
# ---------------------------------------------------------------------------
mx <- suppressWarnings(max(m, na.rm = TRUE)); mn <- suppressWarnings(min(m, na.rm = TRUE))
frac_int <- mean(abs(m - round(m)) < 1e-8, na.rm = TRUE)
looks_log <- is.finite(mx) && mx <= 50
n_neg <- sum(m < 0, na.rm = TRUE); frac_neg <- n_neg / length(m)

msg <- character(0); already_norm <- FALSE
if (looks_log) {
    input_type <- "log-scale"
    matrix_norm <- m
    msg <- c(msg, "The uploaded matrix looks already log-scale/normalized: normalization step skipped.")
} else {
    input_type <- if (frac_int > 0.99) "raw integer counts" else "linear non-integer (RSEM/TPM-like)"
    if (n_neg > 0) {
        msg <- c(msg, sprintf("Input is linear-scale but contains %d negative values; they were clipped to 0 before normalization.", n_neg))
        m[m < 0] <- 0
    }
    suppressPackageStartupMessages(library(DESeq2))
    # Size factors are estimated on the rounded matrix (DESeq2 needs integers)
    # but APPLIED to the unrounded one, so non-integer RSEM/TPM values keep
    # their precision. Falls back to 'poscounts' when no gene is non-zero in
    # every sample (sparse or small-panel data).
    m_int <- round(m)
    sf <- tryCatch(estimateSizeFactorsForMatrix(m_int),
                   error = function(e) {
                       msg <<- c(msg, "Median-of-ratios size factors could not be computed (no gene expressed in every sample); used DESeq2 'poscounts' size factors instead.")
                       estimateSizeFactorsForMatrix(m_int, type = "poscounts")
                   })
    sf_ratio <- if (is.finite(max(sf)) && min(sf) > 0) max(sf) / min(sf) else Inf
    cs <- colSums(m, na.rm = TRUE)
    equal_sums <- ncol(m) > 1 && is.finite(mean(cs)) && mean(cs) > 0 && sd(cs) / mean(cs) < 0.01
    nz <- m[m > 0]; frac_int_nz <- if (length(nz)) mean(abs(nz - round(nz)) < 1e-8) else 1
    # A linear matrix that is ALREADY library-size normalised cannot be told from raw
    # counts by its value range, but it leaves fingerprints: (a) every size factor is
    # ~1 (median-of-ratios is idempotent on the cohort it was applied to); (b) every
    # column sums to the same total (TPM/CPM); (c) the non-zero values are essentially
    # never integers (counts divided by a size factor) while library depths are
    # already similar. Raw counts (STAR/HTSeq: integers), salmon/kallisto (mostly
    # integers) and cBioPortal RSEM (~12% integers) do not trip these tests.
    # When one fires the matrix is passed through UNCHANGED (re-normalising an
    # already normalised matrix is never wanted) and the GUI shows a warning.
    already_norm <- ncol(m) > 1 && (sf_ratio < 1.05 || equal_sums || (frac_int_nz < 0.005 && sf_ratio < 1.5))
    if (already_norm) {
        input_type <- "linear, already normalised (passthrough)"
        matrix_norm <- m
        msg <- c(msg, "The uploaded matrix looks already log-scale/normalized: normalization step skipped.")
    } else {
        matrix_norm <- sweep(m, 2, sf, "/")
        msg <- c(msg, sprintf("DESeq2 median-of-ratios size factors applied (range %.3f-%.3f); norm_data.csv is on the linear scale.", min(sf), max(sf)))
    }
}

# ---------------------------------------------------------------------------
# 2. Optional batch correction. limma::removeBatchEffect assumes continuous
#    log-scale data, so linear matrices are corrected on log2(x+1) and mapped
#    back to the linear scale (2^y - 1, clipped at 0) to keep norm_data.csv
#    on one consistent scale for annotator.R.
# ---------------------------------------------------------------------------
batch_applied <- FALSE
if (batch_bool && batch_col %in% colnames(col_data) && ncol(matrix_norm) > 1) {
    suppressPackageStartupMessages(library(limma))
    vector_batch <- col_data[[batch_col]]
    if (length(unique(vector_batch)) > 1) {
        if (looks_log) {
            matrix_norm <- removeBatchEffect(matrix_norm, batch = vector_batch)
        } else {
            lg <- log2(pmax(matrix_norm, 0) + 1)
            lg <- removeBatchEffect(lg, batch = vector_batch)
            matrix_norm <- pmax(2^lg - 1, 0)
        }
        batch_applied <- TRUE
        msg <- c(msg, sprintf("Batch correction applied (limma::removeBatchEffect on the log2 scale, column '%s', %d batches).", batch_col, length(unique(vector_batch))))
    } else {
        msg <- c(msg, sprintf("Batch correction requested but column '%s' has a single level - not applied.", batch_col))
    }
}

matrix_norm <- as.data.frame(matrix_norm)
rownames(matrix_norm) <- rownames(counts)
# data.table::fwrite is ~20x faster than write.csv on a 60k x 1000 matrix (same
# values, full precision); fall back to write.csv if data.table is unavailable.
if (requireNamespace("data.table", quietly = TRUE)) {
    data.table::fwrite(data.frame(Gene = rownames(matrix_norm), matrix_norm, check.names = FALSE),
                       file = file.path(output_fold, "norm_data.csv"), quote = FALSE)
} else {
    write.csv(matrix_norm, file = file.path(output_fold, "norm_data.csv"), quote = FALSE)
}

writeLines(c(paste0("input_type: ", input_type), paste0("already_normalised_passthrough: ", if (already_norm) "yes" else "no"), msg), file.path(output_fold, "norm_method.txt"))
cat(paste0(if (looks_log || n_neg > 0 || already_norm) "WARNING: " else "", paste(msg, collapse = " ")), "\n")
