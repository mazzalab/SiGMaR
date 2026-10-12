if (!requireNamespace("BiocManager", quietly=TRUE)) install.packages("BiocManager")

# Pacchetti mancanti che non hanno Conda build
BiocManager::install("GSVA")
BiocManager::install("jsonlite")  # se non presente