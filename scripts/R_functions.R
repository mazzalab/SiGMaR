library(dplyr)
library(GSVA)
library(GSEABase)
library(edgeR)
library(AnnotationDbi)
library(org.Hs.eg.db)
library(readr)
library(jsonlite)

write_gct <- function(df, file_path) {
  
  mat_data <- df[, sapply(df, is.numeric), drop = FALSE]

  mat <- as.matrix(mat_data)
  class(mat) <- "numeric"

  num_genes <- nrow(df)
  num_samples <- ncol(df)

  line1 <- "#1.2"
  line2 <- paste(num_genes, num_samples, sep="\t")
  writeLines(c(line1, line2), file_path)

  out_df <- data.frame(
    Name = rownames(df),
    Description = rownames(df),
    mat,
    check.names = FALSE
  )

  write.table(out_df, file = file_path, append = TRUE, 
              sep = "\t", quote = FALSE, row.names = FALSE, col.names = TRUE)

  # sample_cols <- setdiff(colnames(df), "Gene")
  # n_genes   <- nrow(df)
  # n_samples <- length(sample_cols)
  # con <- file(out_file, open = "wt")
  # writeLines("#1.2", con)
  # writeLines(paste(n_genes, n_samples, sep = "\t"), con)
  # writeLines(paste(c("Name", "Description", sample_cols), collapse = "\t"), con)
  # body <- cbind(Name = df$Gene, Description = df$Gene, as.matrix(df[, sample_cols]))
  # write.table(body, con, sep = "\t", quote = FALSE, row.names = FALSE, col.names = FALSE)
  # close(con)
}

gct_convert = function(df){

  df_for_gct <- df %>%
    mutate(Gene = rownames(.)) %>%
    dplyr::select(Gene, everything())

  # convert in gct file
  gct_path <- file.path(output_fold, "gct_count.gct")
  write_gct(df_for_gct, gct_path)

  return(list(gct_path=gct_path, df=df))
}

ntp_template <- function(centroid_path, output_fold){

  feature_exp <- read_delim(centroid_path, show_col_types = FALSE)

  if ("Gene" %in% colnames(feature_exp)) {
    # Se esiste, la mettiamo al primo posto
    feature_exp <- feature_exp %>% 
      dplyr::select(Gene, everything())
  } else {
    # Se NON esiste, prendiamo l'ultima colonna (dove nel tuo caso sono i nomi)
    # e la rinominiamo in Gene portandola all'inizio
    feature_exp <- feature_exp %>% 
      dplyr::select(Gene = 1, everything())
  }
  feature_exp <- feature_exp[, !duplicated(colnames(feature_exp))]

  # --- SIGNATURE EXTRACTION: top-N most-SPECIFIC genes per class ---
  # Previous logic kept genes with centroid value > 0.5 and assigned each to its
  # single highest class. On z-scored mean centroids with an imbalanced cohort the
  # MAJORITY class sits near 0 (it defines the z-score centre), so no gene cleared
  # the threshold and that class got ZERO template genes -> NTP returned NA for all
  # samples (the MESO crash). We now pick, for each class, the top-N genes by
  # SPECIFICITY = centroid[class] - max(centroid of the other classes). Specificity
  # captures a marker even when its own value is ~0 as long as it is lower in the
  # other classes (e.g. calretinin/CALB2 for epithelioid MESO), and it guarantees
  # every class receives marker genes regardless of the centroid's scale/imbalance.
  centroid_cols <- colnames(feature_exp)[-1]
  class_map <- setNames(1:length(centroid_cols), centroid_cols)
  N_PER_CLASS <- 100

  mat <- as.matrix(feature_exp[, centroid_cols, drop = FALSE])
  storage.mode(mat) <- "numeric"
  k <- length(centroid_cols)
  genes_vec <- feature_exp[[1]]

  # Assign each gene to the class it is MOST specific to (argmax of
  # centroid[class] - max(others)), then keep at most N_PER_CLASS genes per
  # class ranked by that specificity. Marker sets are disjoint by construction
  # and no class can be starved. (The previous sequential top-N + duplicate-drop
  # let the FIRST class absorb up to ALL genes whenever the centroid had fewer
  # than N_PER_CLASS x k genes: PAM50's 50 genes all went to Basal, so NTP
  # called every BRCA sample Basal; SARC/MESO/LUSC late classes were starved.)
  spec_mat <- sapply(seq_len(k), function(ci) {
    others <- if (k > 1) apply(mat[, -ci, drop = FALSE], 1, max, na.rm = TRUE) else rep(0, nrow(mat))
    mat[, ci] - others
  })
  spec_ok  <- replace(spec_mat, !is.finite(spec_mat), -Inf)
  best_cl  <- max.col(spec_ok, ties.method = "first")
  best_sp  <- spec_ok[cbind(seq_len(nrow(spec_ok)), best_cl)]
  features_ntp <- do.call(rbind, lapply(seq_len(k), function(ci) {
    idx <- which(best_cl == ci & is.finite(best_sp))
    idx <- idx[order(best_sp[idx], decreasing = TRUE)]
    idx <- head(idx, N_PER_CLASS)
    if (!length(idx)) return(NULL)
    data.frame(ProbeID = genes_vec[idx], GeneName = genes_vec[idx],
               Class = ci, stringsAsFactors = FALSE)
  }))

  out_path <- file.path(output_fold, "features_ntp.txt")
  write_tsv(features_ntp, out_path)
  
  message(paste("### NTP Template generato con successo:", nrow(features_ntp), "geni selezionati ###"))
  
  return(list(out_path=out_path, class_map=class_map))
}

# =============================================================================
# NTP_predict — canonical Nearest Template Prediction (Hoshida 2010 / NTPez)
# -----------------------------------------------------------------------------
# Clean, vectorised implementation of the NTPez.R classification rule (cosine to
# binary class templates over all marker genes, random-gene-set permutation p,
# BH-FDR). The earlier in-house NTPez port under-performed badly because of a
# template-construction defect (see ntp_template); with correct templates the
# canonical rule is used unchanged. Output format (ntp_classification.txt with a
# predict.label column mapped via class_map) is unchanged, so merge.R is untouched.
# =============================================================================
NTP_predict <- function(input.exp.filename, input.features.filename, output.name,
                        class_map, dist.selection = "cosine", nresmpl = 1000,
                        log_transform = TRUE, ref = NULL, ...) {
  # Canonical Nearest Template Prediction (Hoshida 2010, PLoS ONE 5(11):e15543;
  # GenePattern NTPez.R; CMScaller::ntp, Eide 2017). Classification rule:
  #   1. row-standardise the expression (per-gene z-score; log2 first);
  #   2. for each class build a binary template over ALL marker genes
  #      (1 = gene belongs to the class, 0 otherwise);
  #   3. cosine similarity between the sample's marker-gene vector and each
  #      template -- the denominator is the sample's norm over ALL marker genes,
  #      identical for every class, exactly as in NTPez;
  #   4. nearest template = highest cosine; distance = 1 - cosine.
  # Confidence: for each of nresmpl resamples a random gene set of the same
  # total size is drawn from all genes, the same templates are applied, and the
  # null cosines of every class are pooled (nresmpl x K values); p = fraction of
  # null cosines >= the observed nearest-template cosine (NTPez's rank test),
  # floor 1/(nresmpl*K+1); BH-FDR across samples. nresmpl = 1000 = NTP default.
  dir.create(output.name, recursive = TRUE, showWarnings = FALSE)
  gct   <- read.delim(input.exp.filename, skip = 2, header = TRUE,
                      check.names = FALSE, stringsAsFactors = FALSE)
  genes <- as.character(gct[[1]])
  emat  <- as.matrix(gct[, -c(1, 2), drop = FALSE]); storage.mode(emat) <- "numeric"
  rownames(emat) <- genes
  emat  <- emat[!duplicated(genes), , drop = FALSE]

  if (isTRUE(log_transform)) emat <- log2(pmax(emat, 0) + 1)   # skip when the caller already supplies log-scale data
  # gene-wise standardisation against the fixed TCGA reference (ref) when
  # available, otherwise within the uploaded cohort (see standardize_genes)
  Z    <- standardize_genes(emat, ref)
  ok   <- rowSums(is.finite(Z)) > 0
  Z    <- Z[ok, , drop = FALSE]
  Z[!is.finite(Z)] <- 0

  tmpl    <- read.delim(input.features.filename, stringsAsFactors = FALSE)  # ProbeID, GeneName, Class
  tmpl    <- tmpl[tmpl$ProbeID %in% rownames(Z), , drop = FALSE]
  tmpl    <- tmpl[!duplicated(tmpl$ProbeID), , drop = FALSE]
  classes <- sort(unique(tmpl$Class)); K <- length(classes)
  inv_map <- setNames(names(class_map), as.character(class_map))
  S <- colnames(Z); nS <- length(S)
  Tm <- sapply(classes, function(cl) as.numeric(tmpl$Class == cl))         # genes x K
  if (is.null(dim(Tm))) Tm <- matrix(Tm, ncol = K)
  tnorm <- sqrt(colSums(Tm^2))                                              # sqrt(n_class)

  cos_to_templates <- function(X) {                                         # X: markers x samples
    num <- t(Tm) %*% X                                                      # K x samples
    den <- outer(tnorm, sqrt(colSums(X^2)))                                 # K x samples
    out <- num / den; out[!is.finite(out)] <- -Inf; out
  }
  X   <- Z[tmpl$ProbeID, , drop = FALSE]
  cs  <- cos_to_templates(X)                                                # K x samples
  best <- max.col(t(cs), ties.method = "first")
  obscos <- cs[cbind(best, seq_len(nS))]
  pidx <- ifelse(is.finite(obscos), as.character(classes[best]), NA_character_)
  dtt  <- ifelse(is.finite(obscos), 1 - obscos, NA_real_)

  nresmpl <- as.integer(nresmpl)
  p.value <- rep(NA_real_, nS); BH.FDR <- rep(NA_real_, nS)
  nfeat <- nrow(X); G <- nrow(Z)
  if (nresmpl > 0 && nfeat > 0 && any(is.finite(obscos))) {
    set.seed(7392854)                                                       # NTPez default seed
    ge <- rep(0, nS)
    for (p in seq_len(nresmpl)) {
      r  <- sample.int(G, nfeat)
      cr <- cos_to_templates(Z[r, , drop = FALSE])                          # K x samples null cosines
      ge <- ge + colSums(sweep(cr, 2, obscos, ">="))
    }
    p.value <- (ge + 1) / (nresmpl * K + 1)
    p.value[!is.finite(obscos)] <- NA_real_
    BH.FDR  <- p.adjust(p.value, method = "BH")
  }

  out <- data.frame(sample.names = S, predict.label = inv_map[pidx],
                    dist.to.template = dtt, p.value = p.value, BH.FDR = BH.FDR,
                    stringsAsFactors = FALSE)
  write.table(out, file.path(output.name, "ntp_classification.txt"),
              quote = FALSE, sep = "\t", row.names = FALSE)
  message("### NTP (canonical Hoshida cosine nearest-template + ", nresmpl,
          "-resample FDR) done: ", nS, " samples ###")
  invisible(out)
}

# (The original GenePattern NTPez port was removed: superseded by NTP_predict above.)

# =============================================================================
# Fixed-reference gene standardisation
# -----------------------------------------------------------------------------
# Centroid correlation, ssGSEA and NTP all standardise expression gene-wise.
# Standardising against the uploaded cohort's own mean/sd makes every call depend
# on which other samples were uploaded (a subtype-homogeneous cohort is forced
# to split; a single sample cannot be classified at all). The tool therefore
# ships, per tumour, the gene-wise mean and sd of log2(size-factor normalised
# counts + 1) in the TCGA reference cohort (utilities/reference_stats/
# <tumor>_genes.tsv) and the per-gene-set mean/sd of the raw ssGSEA scores on
# the same cohort (<tumor>_ssgsea.tsv). A sample is standardised against those
# fixed values, so its call is independent of the rest of the upload. On the
# reference cohort itself the result is identical to within-cohort
# standardisation by construction. Genes missing from the reference (or tumours
# without a reference file) fall back to within-cohort standardisation.
# =============================================================================
load_reference_stats <- function(tumor_key, kind = "genes") {
  f <- file.path("utilities", "reference_stats", paste0(tolower(tumor_key), "_", kind, ".tsv"))
  if (!file.exists(f)) return(NULL)
  out <- tryCatch(read.delim(f, stringsAsFactors = FALSE, check.names = FALSE), error = function(e) NULL)
  if (is.null(out) || !all(c("mean", "sd") %in% names(out))) return(NULL)
  out
}

standardize_genes <- function(m, ref = NULL, calibrate = TRUE) {
  m <- as.matrix(m); storage.mode(m) <- "numeric"
  mu  <- rowMeans(m, na.rm = TRUE)
  sdv <- apply(m, 1, sd, na.rm = TRUE)
  n_ref <- 0L; slopes <- NULL
  if (!is.null(ref) && "Gene" %in% names(ref)) {
    idx <- match(rownames(m), ref$Gene); has <- !is.na(idx)
    mu[has]  <- ref$mean[idx[has]]
    sdv[has] <- ref$sd[idx[has]]
    n_ref <- sum(has)
    # Per-sample affine calibration onto the reference scale. Data from another
    # platform/pipeline (FPKM, microarray, a different quantifier) sit on a
    # different scale than the TCGA reference (SCAN-B log2 FPKM: gene means 1.6
    # vs 8.3 in the reference; raw reference z-scores median -7.6 -> 38% centroid
    # concordance). For each sample we fit x ~ a + b * mu over the shared genes
    # and map x' = (x - a) / b before standardising; on the reference cohort
    # itself b ~ 1, a ~ 0 and the calls are unchanged (98-99% identical), on
    # SCAN-B concordance rises to 89%. Two parameters per sample, so the call
    # stays independent of the other uploaded samples.
    if (isTRUE(calibrate) && n_ref >= 200) {
      mu_h <- mu[has]
      for (j in seq_len(ncol(m))) {
        x <- m[has, j]; ok <- is.finite(x) & is.finite(mu_h)
        if (sum(ok) < 200) next
        b <- stats::cov(x[ok], mu_h[ok]) / stats::var(mu_h[ok]); a <- mean(x[ok]) - b * mean(mu_h[ok])
        if (!is.finite(b) || b < 0.2) next
        m[has, j] <- (x - a) / b
        slopes <- c(slopes, b)
      }
    }
  }
  sdv[!is.finite(sdv) | sdv <= 0] <- NA_real_
  z <- (m - mu) / sdv
  attr(z, "n_reference_genes") <- n_ref
  attr(z, "calibration_slopes") <- slopes
  z
}

# Raw ssGSEA scores (gene sets x samples) for the centroid-derived sets. The sets
# are sign-split: for each subtype, UP = genes whose centroid value is >= thr_up,
# DOWN = genes <= thr_dn (with the default +/-0.02 on centred centroids this is
# effectively the sign of the centroid value). normalize = FALSE so that a score
# does not depend on the range of the other samples in the upload.
ssgsea_scores = function(df, centroid_path, thr_up=0.02, thr_dn=-0.02, universe = NULL){
  rna_normM <- as.matrix(df)
  storage.mode(rna_normM) <- "numeric"
  rownames(rna_normM) <- rownames(df)
  # Fixed gene universe. A raw ssGSEA score depends on which genes are in the
  # matrix (rank positions and their number), so scores from a 19k-gene upload
  # are not comparable with reference statistics from the 35k-gene TCGA matrix.
  # When the reference gene table is supplied, the matrix is rebuilt on exactly
  # the reference genes: genes present keep their values, genes absent from the
  # upload take their reference mean (a constant across samples), extra genes are
  # dropped. On the reference cohort itself this is the identity.
  if (!is.null(universe) && all(c("Gene", "mean") %in% names(universe))) {
    g <- as.character(universe$Gene); mu <- as.numeric(universe$mean)
    U <- matrix(rep(mu, ncol(rna_normM)), nrow = length(g), dimnames = list(g, colnames(rna_normM)))
    present <- intersect(g, rownames(rna_normM))
    U[present, ] <- rna_normM[present, , drop = FALSE]
    message("ssGSEA: reference gene universe (", length(g), " genes; ", length(present), " present in the upload, ",
            length(g) - length(present), " imputed at their reference mean)")
    rna_normM <- U
  }

  # ---- load centroid table (THIS is what you called feature_exp before) ----
  feature_exp <- as.data.frame(read_delim(centroid_path))
  if ("Gene" %in% colnames(feature_exp)) {
    feature_exp <- feature_exp %>% dplyr::select(Gene, everything())
  } else {
    feature_exp <- feature_exp %>% dplyr::select(Gene = 1, everything())
  }

  centroid_cols <- colnames(feature_exp)[-1]

  # ---- thresholds (requested) ----

  feat_long <- feature_exp %>%
    pivot_longer(all_of(centroid_cols), names_to = "centroid_name", values_to = "centroid") %>%
    mutate(
      cluster = centroid_name,
      direction = case_when(
        centroid >= thr_up ~ "UP",
        centroid <= thr_dn ~ "DOWN",
        TRUE ~ NA_character_
      )
    ) %>%
    filter(!is.na(direction)) %>%
    mutate(Gene = as.character(Gene))

  # ---- build GeneSets; keep only genes present in expression ----
  genesets_tbl <- feat_long %>%
    group_by(cluster, direction) %>%
    summarise(genes = list(unique(Gene)), .groups = "drop") %>%
    mutate(
      genes = lapply(genes, function(g) intersect(g, rownames(rna_normM))),
      setName = paste0(cluster, "_", direction)
    ) %>%
    filter(lengths(genes) > 0) %>%
    mutate(GeneSet = purrr::map2(genes, setName, ~ GeneSet(.x, setName = .y)))

  genesets <- setNames(genesets_tbl$GeneSet, genesets_tbl$setName)
  gsc <- GeneSetCollection(genesets)

  # sanity check: sizes
  set_sizes <- sapply(gsc, function(gs) length(geneIds(gs)))
  print(set_sizes)

  # ---- ssGSEA ----
  param <- ssgseaParam(
    exprData  = rna_normM,
    geneSets  = gsc,
    minSize   = 10,     # I strongly recommend >1; 10 is safer
    maxSize   = Inf,
    alpha     = 0.25,
    normalize = FALSE
  )

  ssgsea.res <- gsva(param)  # geneSet x sample matrix
  list(scores = ssgsea.res, centroid_cols = centroid_cols)
}

ssgsea_range_normalise <- function(es) {
  rng <- apply(es, 2, function(v) { v <- v[is.finite(v)]; if (length(v) < 2) NA_real_ else max(v) - min(v) })
  rng[!is.finite(rng) | rng <= 0] <- NA_real_
  sweep(es, 2, rng, "/")
}

ssgsea_fun = function(df, centroid_path, outpath, thr_up=0.02, thr_dn=-0.02, ref_sets = NULL, ref_genes = NULL){

  ssgesea_outpath=file.path(outpath, "ssGSEA")
  dir.create(ssgesea_outpath)

  # Raw scores on the reference gene universe (see ssgsea_scores): identical to
  # the plain computation on the reference cohort, comparable with the reference
  # statistics for uploads with a different gene set. (Per-sample range
  # normalisation was tried and rejected: it fixed the cross-matrix scale but cost
  # 4-27 points on the TCGA cohorts.)
  use_universe <- !is.null(ref_sets) && "scale" %in% names(ref_sets) && all(ref_sets$scale == "reference_universe") && !is.null(ref_genes)
  sc <- ssgsea_scores(df, centroid_path, thr_up, thr_dn, universe = if (use_universe) ref_genes else NULL)
  ssgsea.res <- sc$scores; centroid_cols <- sc$centroid_cols

  # ---- z-score per gene set: against the fixed reference cohort when available
  #      (utilities/reference_stats/<tumor>_ssgsea.tsv: Set, mean, sd of the raw
  #      scores on the reference universe; column 'scale' = "reference_universe"),
  #      otherwise across the uploaded samples ----
  if (use_universe && all(c("Set", "mean", "sd") %in% names(ref_sets)) && all(rownames(ssgsea.res) %in% ref_sets$Set)) {
    idx <- match(rownames(ssgsea.res), ref_sets$Set)
    ssgsea.z <- (ssgsea.res - ref_sets$mean[idx]) / ref_sets$sd[idx]
    message("ssGSEA: scores standardised against the reference cohort (", length(idx), " sets)")
  } else {
    if (!is.null(ref_sets)) message("ssGSEA: reference set statistics missing/old format (need scale = reference_universe) -> within-cohort standardisation")
    ssgsea.z <- t(scale(t(ssgsea.res)))
  }

  # ---- Combine UP and DOWN per cluster: score = UP - DOWN ----
  combine_cluster_score <- function(zmat, cluster_prefix){
    up_name   <- paste0(cluster_prefix, "_UP")
    down_name <- paste0(cluster_prefix, "_DOWN")
  
    has_up   <- up_name %in% rownames(zmat)
    has_down <- down_name %in% rownames(zmat)
    
    if(!has_up && !has_down) stop(paste("No signature found for", cluster_prefix))
    
    if(has_up && has_down){
      zmat[up_name, , drop=FALSE] - zmat[down_name, , drop=FALSE]
    } else if(has_up){
      zmat[up_name, , drop=FALSE]
    } else {
      -zmat[down_name, , drop=FALSE]
    }
  }

  clusters <- centroid_cols
  cluster_scores <- do.call(rbind, lapply(clusters, function(cl) combine_cluster_score(ssgsea.z, cl)))
  rownames(cluster_scores) <- clusters

  # ---- classify per sample ----
  predicted_cluster <- vapply(seq_len(ncol(cluster_scores)), function(i) {
    x <- cluster_scores[, i]
    valid <- is.finite(x)
    if (!any(valid)) {
      return("Uncertain")
    }
    x[!valid] <- -Inf
    names(x)[which.max(x)]
  }, character(1))
  names(predicted_cluster) <- colnames(cluster_scores)

  # ---- output ----
  combi <- data.frame(
    Sample = colnames(cluster_scores),
    predicted_cluster = predicted_cluster,
    t(cluster_scores),
    check.names = FALSE
  )

  write.table(combi, file = file.path(ssgesea_outpath, "ssgsea_classification.txt"), sep = "\t", quote = F, row.names = F)
}

zscore_normalize <- function(df_num) {
  # df_num: numeric matrix/data.frame with rows=genes, cols=samples
  m <- as.matrix(df_num)
  mu <- rowMeans(m, na.rm = TRUE)
  sd0 <- apply(m, 1, sd, na.rm = TRUE)
  
  # avoid division by zero
  sd0[sd0 == 0 | is.na(sd0)] <- NA_real_
  
  z <- sweep(m, 1, mu, "-")
  z <- sweep(z, 1, sd0, "/")
  as.data.frame(z)
}

cosine_sim <- function(x, y) {
  den <- sqrt(sum(x^2, na.rm = TRUE)) * sqrt(sum(y^2, na.rm = TRUE))
  if (is.na(den) || den == 0) return(NA_real_)
  sum(x * y, na.rm = TRUE) / den
}

neg_euclidean <- function(x, y) {
  # negative distance so higher is "better"
  -sqrt(sum((x - y)^2, na.rm = TRUE))
}

correlate_subtypes <- function(expression_df, signature_df, subtype_columns, sample_column) {
  merged <- inner_join(signature_df, expression_df, by = "Gene")
  
  sample_vector <- merged[[sample_column]]
  results <- lapply(subtype_columns, function(st) {
    centroid <- merged[[st]]
    
    # Pearson correlation
    pear <- suppressWarnings(cor(sample_vector, centroid, method = "pearson", use = "complete.obs"))
    
    # Cosine similarity
    cosv <- cosine_sim(sample_vector, centroid)
    
    # Euclidean distance (negative)
    eucn <- neg_euclidean(sample_vector, centroid)
    
    list(pearson = pear, cosine = cosv, euclidean = eucn)
  })
  names(results) <- subtype_columns
  
  # best subtype per metric
  pearsons  <- sapply(results, `[[`, "pearson")
  cosines   <- sapply(results, `[[`, "cosine")
  euclideans <- sapply(results, `[[`, "euclidean")  # negative distances; higher = closer
  
  best_pearson  <- names(which.max(pearsons))
  best_cosine   <- names(which.max(cosines))
  best_euclidean <- names(which.max(euclideans))
  
  list(
    results = results,
    best_pearson = best_pearson,
    best_cosine = best_cosine,
    best_euclidean = best_euclidean
  )
}

centroid_corr=function(df, centroid_path, outpath, ref = NULL){

    centr_outpath=file.path(outpath, "Centroid_Correlation")
    dir.create(centr_outpath)

    sample_cols <- colnames(df)
    
    feature_exp <- as.data.frame(read_delim(centroid_path, delim=NULL))
    
    if ("Gene" %in% colnames(feature_exp)) {
        feature_exp <- feature_exp %>% dplyr::select(Gene, everything())
    } else {
        # Se non esiste 'Gene', rinominiamo la prima colonna
        colnames(feature_exp)[1] <- "Gene"
        feature_exp <- feature_exp %>% dplyr::select(Gene, everything())
    }

    all_cols <- colnames(feature_exp)
    potential_subtypes <- all_cols[all_cols != "Gene"]

    centroid_cols <- potential_subtypes[sapply(feature_exp[, potential_subtypes, drop=FALSE], is.numeric)]
    
    if(length(centroid_cols) == 0) stop("Errore: Nessuna colonna numerica trovata nel file dei centroidi.")
    
    #centroid_cols <- colnames(feature_exp)[-1]

    # Centroids are used exactly as published / built (already gene-centred
    # profiles). They are NOT re-standardised across the subtype columns: that
    # step collapsed every gene to +/-1/sqrt(2) for two-class schemes and
    # discarded the centroid magnitudes (validated: -4 points LUAD/LUSC, -13
    # points MESO).
    centroid_z <- bind_cols(Gene = feature_exp$Gene,
                            as.data.frame(feature_exp[, centroid_cols, drop = FALSE]))

    # Gene-wise standardisation of the samples against the fixed TCGA reference
    # (ref) when available, otherwise within the uploaded cohort.
    ngs_z <- as.data.frame(standardize_genes(df[, sample_cols, drop = FALSE], ref))
    rnaseq_z <- bind_cols(Gene = row.names(df), ngs_z)

    # ---- Run per sample and build summary ----
    summary_df_final <- tibble()

    for (s in sample_cols) {
    out <- correlate_subtypes(
        expression_df   = rnaseq_z,
        signature_df    = centroid_z,
        subtype_columns = centroid_cols,
        sample_column   = s
    )

    res <- out$results
    top_pearson  <- max(sapply(res, `[[`, "pearson"), na.rm = TRUE)
    top_cosine   <- max(sapply(res, `[[`, "cosine"), na.rm = TRUE)
    top_euclid   <- max(sapply(res, `[[`, "euclidean"), na.rm = TRUE)
    
    summary_df_temp <- tibble(
        `Subtype System` = tools::file_path_sans_ext(basename(centroid_path)),
        `Assigned Subtype Pearson`   = out$best_pearson,
        `Assigned Subtype Cosine`    = out$best_cosine,
        `Assigned Subtype Euclidean` = out$best_euclidean,
        `Top Pearson` = round(top_pearson, 5),
        `Top Cosine`  = round(top_cosine,  5),
        `Top Euclidean (neg)` = round(top_euclid, 5),
        Sample = s
    )
    
    summary_df_final <- bind_rows(summary_df_final, summary_df_temp)
    }

    # ---- Save ----
    write.table(summary_df_final, file.path(centr_outpath, "centroid_corr_classification.txt"), sep = "\t", quote = F, row.names = F)
}

# Funzione di utilità per ottenere i nomi corretti
get_tumor_filenames <- function(tumor_type) {

  TUMOR_MAP <- list(
    "ov"    = list(json = "OV",      txt = "ov"),
    "brca"  = list(json = "BRCA",    txt = "brca_pam50"),
    "brca_pam50"  = list(json = "BRCA",    txt = "brca_pam50"),
    "paad"  = list(json = "PAAD",    txt = "pdac"),
    "pdac"  = list(json = "PAAD",    txt = "pdac"),
    "hnsc"  = list(json = "HNSC",    txt = "hnscc"),
    "hnscc" = list(json = "HNSC",    txt = "hnscc"),
    "gbm"   = list(json = "LGGGBM",  txt = "gbm"),
    "lusc"  = list(json = "LUSC",    txt = "lusc"),
    "luad"  = list(json = "LUAD",    txt = "luad"),
    "coad"  = list(json = "COADREAD", txt = "coad"),
    "read"  = list(json = "COADREAD", txt = "coad"),
    "meso"  = list(json = "MESO",    txt = "meso"),
    "sarc"  = list(json = "SARC",    txt = "sarc"),
    "blca"  = list(json = "BLCA",    txt = "bladder"),
    "bladder"  = list(json = "BLCA",    txt = "bladder")
  )

  t <- tolower(tumor_type)
  if (t %in% names(TUMOR_MAP)) {
    return(TUMOR_MAP[[t]])
  } else {
    # Default: se non in lista, usa il codice passato (es. SKCM -> json: SKCM, txt: skcm)
    return(list(json = toupper(t), txt = t))
  }
}

input_for_tmp=function(df, output_fold){

  tmp_outpath=file.path(output_fold, "TMP")
  dir.create(tmp_outpath)

  df$Gene=rownames(df)

  # 1. Recupera il percorso del file annotator.R (funziona con Rscript)
  args_raw <- commandArgs(trailingOnly = FALSE)
  file_arg <- grep("--file=", args_raw, value = TRUE)

  if (length(file_arg) > 0) {
      # Estrae il path e lo normalizza (es: /home/user/project/scripts/annotator.R)
      script_path <- normalizePath(sub("--file=", "", file_arg))
      # Directory degli script (es: /home/user/project/scripts)
      script_dir <- dirname(script_path)
      # Root del progetto (sale di un livello: /home/user/project)
      project_root <- dirname(script_dir)
  } else {
      # Fallback se lo lanci da RStudio o terminale interattivo
      project_root <- getwd()
  }

  # 2. Definisci il path assoluto verso utilities
  # Assumendo che utilities sia allo stesso livello della cartella scripts
  utilities_path <- file.path(project_root, "utilities")

  tumor_info <- get_tumor_filenames(tumor_type)
  json_path <- file.path(utilities_path, "ft_name_convert", 
                        paste0("entrez2tmp_", tumor_info$json, "_GEXP.json"))

  x <- fromJSON(json_path)

  df_map <- data.frame(
    Entrez_Gene_Id   = names(x),
    value = unlist(x, use.names = FALSE),
    stringsAsFactors = FALSE,
    row.names = NULL
  )

  df_map$Hugo_Symbol <- sub("^N:GEXP::([^:]+):.*$", "\\1", df_map$value)

  df_map <- filter(df_map, Hugo_Symbol != "?")

  df_map <- df_map[,c("Entrez_Gene_Id", "Hugo_Symbol")]

  colnames(df)[colnames(df) == "Gene"] <- "Hugo_Symbol"

  df2 <- df %>%
    left_join(df_map, by = "Hugo_Symbol")

  # 4) find genes in df_map missing from df2 (by Hugo_Symbol)
  missing_symbols <- setdiff(df_map$Hugo_Symbol, df2$Hugo_Symbol)

  # 5) build missing rows with zeros for all sample columns
  sample_cols <- setdiff(colnames(df2), c("Hugo_Symbol", "Entrez_Gene_Id"))

  missing_rows <- df_map %>%
    filter(Hugo_Symbol %in% missing_symbols) %>%
    mutate(!!!setNames(rep(list(0), length(sample_cols)), sample_cols)) %>%
    dplyr::select(all_of(colnames(df2)))

  # 6) bind
  df_complete <- bind_rows(df2, missing_rows)

  # if you want a base data.frame (not tibble)
  df_complete <- filter(df_complete, Hugo_Symbol != "?")
  df_complete <- filter(df_complete, !is.na(Entrez_Gene_Id))
  df_complete[is.na(df_complete)] <- 0

  samples <- setdiff(colnames(df_complete), c("Hugo_Symbol", "Entrez_Gene_Id"))
  df_complete <- df_complete[, c("Hugo_Symbol", 
                                "Entrez_Gene_Id",
                                samples)]
  write.table(df_complete, file.path(tmp_outpath, "tmp_data.txt"), sep = "\t", row.names = F, quote = F)

  return(json_path)
}

consensus_ov_eval=function(df, outpath){
  
  library(consensusOV)
  
  ov_outpath=file.path(outpath, "Consensus_OV")
  dir.create(ov_outpath, recursive = TRUE, showWarnings = FALSE)

  dat=df

  dat$Gene=rownames(dat)

  stopifnot("Gene" %in% names(dat))

  genes <- dat$Gene
  cts   <- dat[, setdiff(names(dat), "Gene"), drop = FALSE]

  # strict column order, silent coercion
  cts[] <- lapply(cts, function(x) suppressWarnings(as.numeric(x)))
  cts   <- as.matrix(cts)
  mode(cts) <- "numeric"

  # drop rows with no finite values
  keep_rows <- rowSums(is.finite(cts)) > 0
  cts   <- cts[keep_rows, , drop = FALSE]
  genes <- genes[keep_rows]

  ## ---- 3) Use input matrix directly ----
  expr_matrix <- cts
  rownames(expr_matrix) <- genes

  ## ---- 4) Map to ENTREZ (auto-detect SYMBOL vs ENSEMBL) ----
  is_ens <- grepl("^ENSG\\d", genes)

  if (all(is_ens)) {
    key_type <- "ENSEMBL"
    keys_vec <- sub("\\.\\d+$", "", genes)   # strip version
  } else if (all(!is_ens)) {
    key_type <- "SYMBOL"
    keys_vec <- genes
  } else {
    # mixed IDs — default to SYMBOL unless you prefer ENSEMBL
    key_type <- "SYMBOL"
    keys_vec <- genes
    warning(sprintf("Mixed ID types detected (%d ENSEMBL, %d non-ENSEMBL). Using keytype = %s.",
                    sum(is_ens), sum(!is_ens), key_type))
  }

  entrez <- AnnotationDbi::mapIds(
    org.Hs.eg.db,
    keys     = keys_vec,
    keytype  = key_type,
    column   = "ENTREZID",
    multiVals = "first"
  )
  names(entrez) <- genes

  ## ---- 5) Keep mapped rows; collapse duplicate ENTREZ by mean ----
  has_entrez <- !is.na(entrez) & nzchar(entrez)
  expr_mapped <- expr_matrix[has_entrez, , drop = FALSE]
  entrez2    <- entrez[has_entrez]

  if (nrow(expr_mapped) == 0) {
    stop("Consensus OV failed: no genes could be mapped to Entrez IDs.")
  }

  # rowsum -> mean per ENTREZ
  mat_sum <- rowsum(expr_mapped, group = entrez2, reorder = FALSE)
  grp_n   <- as.integer(table(entrez2)[rownames(mat_sum)])
  expr_unique <- mat_sum / grp_n
  stopifnot(all(!duplicated(rownames(expr_unique))))

  cat(sprintf("Rows with ENTREZ kept: %d of %d\n",
              nrow(expr_unique), nrow(expr_matrix)))

  ## ---- 6) Call subtypes (consensusOV) ----
  # Full interface with probabilities
  res_full <- get.consensus.subtypes(
    expression.matrix      = expr_unique,
    entrez.ids             = rownames(expr_unique),
    concordant.tumors.only = TRUE,
    remove.using.cutoff    = FALSE
  )

  ## ---- 7) Collect outputs ----
  labels <- res_full$consensusOV.subtypes                 # factor per sample
  probs  <- as.data.frame(res_full$rf.probs)              # per-subtype probs
  sample_names <- rownames(res_full$rf.probs)
  probs$sample <- sample_names
  probs <- dplyr::relocate(probs, sample)

  # margin = top_prob - second_best (confidence)
  margin_vec <- margin(res_full$rf.probs)

  summary_df <- tibble::tibble(
    sample    = sample_names,
    subtype   = as.character(labels),
    margin    = as.numeric(margin_vec)
  )

  # write csv 
  readr::write_csv(summary_df, file.path(ov_outpath,"consensusOV_labels_margins.csv"))
  readr::write_csv(probs, file.path(ov_outpath,"consensusOV_probabilities.csv"))
}

cms=function(df, output_fold, df_linear = NULL, rnaseq_counts = TRUE){
  # df        : log2-scale matrix (CMSclassifier RF/SSP expect log2 normalized expression)
  # df_linear : linear-scale matrix for CMScaller, which log-transforms internally when RNAseq = TRUE
  if (is.null(df_linear)) df_linear <- df

  library(CMSclassifier)
  library(AnnotationDbi)
  library(org.Hs.eg.db)
  library(CMScaller)
  library(Biobase)

  ov_outpath <- file.path(output_fold, "CMS")
  dir.create(ov_outpath, recursive = TRUE, showWarnings = FALSE)

  data_pre <- as.data.frame(df)
  gene_ids <- rownames(data_pre)
  if (is.null(gene_ids) || anyNA(gene_ids) || !length(gene_ids)) {
    stop("CMS failed: gene identifiers are missing from the input matrix.")
  }

  expr_mat <- as.matrix(data_pre)
  storage.mode(expr_mat) <- "numeric"
  rownames(expr_mat) <- gene_ids

  keep_rows <- rowSums(is.finite(expr_mat)) > 0
  expr_mat <- expr_mat[keep_rows, , drop = FALSE]
  gene_ids <- gene_ids[keep_rows]

  if (nrow(expr_mat) == 0) {
    stop("CMS failed: no numeric expression rows were available after cleaning.")
  }

  # ---- Map to ENTREZ (auto-detect SYMBOL vs ENSEMBL, like Consensus OV) ----
  is_ens <- grepl("^ENSG\\d", gene_ids)
  if (all(is_ens)) {
    key_type <- "ENSEMBL"
    keys_vec <- sub("\\.\\d+$", "", gene_ids)
  } else if (all(!is_ens)) {
    key_type <- "SYMBOL"
    keys_vec <- gene_ids
  } else {
    key_type <- "SYMBOL"
    keys_vec <- gene_ids
    warning(sprintf("Mixed ID types detected (%d ENSEMBL, %d non-ENSEMBL). Using keytype = %s.",
                    sum(is_ens), sum(!is_ens), key_type))
  }

  entrez_ids <- AnnotationDbi::mapIds(
    org.Hs.eg.db,
    keys = keys_vec,
    keytype = key_type,
    column = "ENTREZID",
    multiVals = "first"
  )
  names(entrez_ids) <- gene_ids

  keep <- !is.na(entrez_ids) & nzchar(entrez_ids)
  expr_mapped <- expr_mat[keep, , drop = FALSE]
  entrez_ids <- entrez_ids[keep]

  if (nrow(expr_mapped) == 0) {
    stop("CMS failed: no genes could be mapped to Entrez IDs.")
  }

  expr_unique <- rowsum(expr_mapped, group = entrez_ids, reorder = FALSE)
  grp_n <- as.integer(table(entrez_ids)[rownames(expr_unique)])
  expr_unique <- expr_unique / grp_n
  stopifnot(all(!duplicated(rownames(expr_unique))))

  cat("CMS input:", nrow(expr_unique), "genes x", ncol(expr_unique), "samples\n\n")

  cms_input <- as.data.frame(expr_unique, check.names = FALSE)

  ### CMS classifier
  # ---- Run both methods (errors NOT silenced) ----
  cms_out <- tryCatch(
    CMSclassifier::classifyCMS(cms_input, method = c("RF", "SSP")),
    error = function(e) {
      stop("CMS classifier error: ", conditionMessage(e))
    }
  )

  Rfcms <- cms_out$RF.details
  SScms <- cms_out$SSP.details

  if (is.null(Rfcms) || is.null(SScms)) {
    # fallback to the direct predictors if the wrapper structure differs
    rf_raw <- tryCatch(
      CMSclassifier::classifyCMS.RF(cms_input),
      error = function(e) {
        stop("CMS RF error: ", conditionMessage(e))
      }
    )
    ss_raw <- tryCatch(
      CMSclassifier::classifyCMS.SSP(cms_input),
      error = function(e) {
        stop("CMS SSP error: ", conditionMessage(e))
      }
    )
    Rfcms <- as.data.frame(rf_raw, check.names = FALSE)
    SScms <- as.data.frame(ss_raw, check.names = FALSE)
  }

  ### CMS Caller (linear-scale input; RNAseq = TRUE -> CMScaller applies its own log2)
  lin_mat <- as.matrix(as.data.frame(df_linear)[rownames(expr_mat), , drop = FALSE]); storage.mode(lin_mat) <- "numeric"
  lin_mapped <- lin_mat[keep, , drop = FALSE]
  lin_unique <- rowsum(lin_mapped, group = entrez_ids, reorder = FALSE) / grp_n
  cms_caller_input <- as.data.frame(lin_unique, check.names = FALSE)
  pdf(file.path(ov_outpath, "cmscaller_plot.pdf"))
    cms_caller_out <- tryCatch(
      CMScaller::CMScaller(cms_caller_input, RNAseq = isTRUE(rnaseq_counts), doPlot = TRUE),
      error = function(e) {
        dev.off()
        stop("CMScaller error: ", conditionMessage(e))
      }
    )
    dev.off()

  # Construct table
  sample_names <- rownames(Rfcms)
  if (is.null(sample_names) || !length(sample_names)) sample_names <- colnames(cms_input)

  cmscaller_pred <- cms_caller_out$prediction[match(sample_names, rownames(cms_caller_out))]
  cmscaller_pred <- ifelse(is.na(cmscaller_pred) | cmscaller_pred == "", "Unknown", cmscaller_pred)
  cmscaller_pred <- ifelse(grepl("^[0-9]+$", cmscaller_pred), paste0("CMS", cmscaller_pred), cmscaller_pred)

  rf_subtype <- as.character(Rfcms$RF.nearestCMS)
  rf_subtype <- ifelse(is.na(rf_subtype) | rf_subtype == "", "Unknown", rf_subtype)
  rf_subtype <- ifelse(grepl("[;,]", rf_subtype), "Unknown", rf_subtype)

  results <- data.frame(
    sample            = sample_names,
    RF_subtype        = rf_subtype,
    SSP_subtype       = SScms$SSP.nearestCMS,
    CMScaller_subtype = cmscaller_pred,
    stringsAsFactors  = FALSE
  )

  print(results)

  write.csv(results, file.path(ov_outpath, "cms_classification.csv"), row.names = FALSE)
  cat("\nSaved to ", file.path(ov_outpath, "cms_classification.csv"), "\n", sep = "")
}


breast_subtype=function(df, output_fold){

  library(BreastSubtypeR)
  library(SummarizedExperiment)
  library(org.Hs.eg.db)
  library(AnnotationDbi)

  brca_outpath=file.path(output_fold, "breast_subtype")
  dir.create(brca_outpath, recursive = TRUE, showWarnings = FALSE)

  # ---- Build expression matrix (genes as rownames) ----
  data_pre <- as.data.frame(df)
  gene_symbols <- rownames(data_pre)
  if (is.null(gene_symbols) || anyNA(gene_symbols) || !length(gene_symbols)) {
    stop("Breast subtype failed: gene identifiers are missing from the input matrix.")
  }

  expr_matrix <- as.matrix(data_pre)
  storage.mode(expr_matrix) <- "numeric"
  rownames(expr_matrix) <- gene_symbols
  expr_matrix <- expr_matrix[rowSums(is.finite(expr_matrix)) > 0, , drop = FALSE]

  # Remove duplicate gene symbols (keep first occurrence)
  expr_matrix <- expr_matrix[!duplicated(rownames(expr_matrix)), , drop = FALSE]
  if (nrow(expr_matrix) == 0) {
    stop("Breast subtype failed: no numeric expression rows were available after cleaning.")
  }

  cat("Matrix:", nrow(expr_matrix), "genes x", ncol(expr_matrix), "samples\n")

  # ---- Build clinical metadata (colData) ----
  # BreastSubtypeR needs ER/PR/HER2 status. Since you don't have it,
  # we use "unknown"/NA which restricts to methods that don't need IHC.
  clinical_df <- data.frame(
    PatientID  = colnames(expr_matrix),
    ER_status  = NA,   # set to "Positive"/"Negative" if known
    PR_status  = NA,
    HER2_status = NA,
    row.names  = colnames(expr_matrix)
  )

  # ---- Build feature annotation ----
  # Map gene symbols to Entrez IDs
  is_ens <- grepl("^ENSG\\d", rownames(expr_matrix))
  if (all(is_ens)) {
    key_type <- "ENSEMBL"
    keys_vec <- sub("\\.\\d+$", "", rownames(expr_matrix))
  } else {
    key_type <- "SYMBOL"
    keys_vec <- rownames(expr_matrix)
  }

  entrez_ids <- mapIds(org.Hs.eg.db,
                       keys = keys_vec,
                       column = "ENTREZID",
                       keytype = key_type,
                       multiVals = "first")

  # Create rowData with the EXACT column name BreastSubtypeR expects
  feature_anno <- S4Vectors::DataFrame(
    probe       = rownames(expr_matrix),
    Gene.symbol = rownames(expr_matrix),
    ENTREZID    = as.character(entrez_ids)   # ← all caps
  )

  # Rebuild SE
  se <- SummarizedExperiment(
    assays  = list(counts = expr_matrix),
    colData = clinical_df,
    rowData = feature_anno
  )

  # Mapping
  se_mapped <- Mapping(
    se,
    RawCounts = FALSE,
    method    = "max",
    impute    = TRUE,
    verbose   = TRUE
  )

  # ---- Run subtyping ----
  results <- BS_Multi(
    se_mapped,
    methods = c("AIMS", "sspbc")
  )

  # ---- Extract subtypes into simple table ----
  simple_results <- data.frame(
    sample      = rownames(results$res_subtypes),
    AIMS        = results$res_subtypes$AIMS,
    sspbc       = results$res_subtypes$sspbc,
    entropy     = results$res_subtypes$entropy,
    stringsAsFactors = FALSE
  )

  # If rownames are empty, use the SE column names
  if (all(simple_results$sample == "")) {
    simple_results$sample <- colnames(se_mapped)
  }

  print(simple_results)

  # ---- Summary ----
  cat("\n--- AIMS distribution ---\n")
  print(table(simple_results$AIMS))
  cat("\n--- sspbc distribution ---\n")
  print(table(simple_results$sspbc))
  cat("\n--- Agreement between methods ---\n")
  print(table(simple_results$AIMS == simple_results$sspbc))

  # ---- Save ----
  write.csv(simple_results,
            file.path(brca_outpath, "breast_subtypes.csv"),
            row.names = FALSE)

  cat("\nSaved to output/breast_subtypes.csv\n")

}
