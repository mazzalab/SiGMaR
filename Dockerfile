# 1. Partiamo da un'immagine Python ufficiale sottile
FROM python:3.10-slim

# 2. Installiamo R e le dipendenze di sistema necessarie per compilare i pacchetti bioinformatici
# Usiamo il client Docker dei repository Debian per evitare problemi di build cross-arch
RUN apt-get update && apt-get install -y \
    r-base \
    git \
    wget \
    tar \
    libcurl4-openssl-dev \
    libssl-dev \
    libxml2-dev \
    libfontconfig1-dev \
    libharfbuzz-dev \
    libfribidi-dev \
    libfreetype6-dev \
    libpng-dev \
    libtiff-dev \
    libjpeg-dev \
    libmagick++-dev \
    libbz2-dev \
    liblzma-dev \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    procps \
    docker.io \
    docker-compose \
    && rm -rf /var/lib/apt/lists/*

# 3. Impostiamo la cartella di lavoro
WORKDIR /app

# 4. Installiamo le dipendenze Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Installiamo BiocManager e i pacchetti R (Bioinformatica)
# Nota: Questa fase è la più lenta ma viene fatta solo una volta durante la creazione dell'immagine
# CMSclassifier: repo Sage-Bionetworks/CMSclassifier rimossa da GitHub (404) -
# vendorizzato in vendor/CMSclassifier (estratto da una build funzionante precedente)
# e installato da lì invece che da remotes::install_github.
COPY vendor/CMSclassifier /usr/local/lib/R/site-library/CMSclassifier
RUN Rscript -e "install.packages('BiocManager', repos='https://cloud.r-project.org/')" \
    && Rscript -e "BiocManager::install(c('DESeq2', 'GSEABase', 'edgeR', 'AnnotationDbi', 'org.Hs.eg.db', 'consensusOV', 'BreastSubtypeR'), update=FALSE, ask=FALSE)" \
    && Rscript -e "install.packages(c('tidyverse', 'jsonlite', 'readr', 'dplyr', 'purrr', 'tidyr', 'tibble', 'remotes'), repos='https://cloud.r-project.org/')" \
    && Rscript -e "remotes::install_github('Lothelab/CMScaller')" \
    && Rscript -e "if (!requireNamespace('CMSclassifier', quietly=TRUE)) stop('CMSclassifier non installato!')" \
    && Rscript -e "if (!requireNamespace('BreastSubtypeR', quietly=TRUE)) stop('BreastSubtypeR non installato!')"

#RUN Rscript -e "BiocManager::install(c('DESeq2', 'GSEABase', 'edgeR', 'AnnotationDbi', 'org.Hs.eg.db', 'consensusOV', 'limma', 'sva', 'genefilter'))"

RUN Rscript -e "install.packages('BiocManager', repos='https://cloud.r-project.org/')" \
    && Rscript -e "BiocManager::install('GSVA', update=FALSE, ask=FALSE)" \
    && Rscript -e "if (!requireNamespace('GSVA', quietly=TRUE)) stop('GSVA non installato!')"

# 6. Copiamo tutto il resto del progetto
COPY . .

# Il modello CloudForest viene fornito a runtime dal filesystem host o dal volume montato.
RUN mkdir -p uploads/temp uploads/results utilities/centroids /app/utilities/gdan-tmp-models/cloudforest/data

# 7. Permessi di esecuzione per gli script
RUN chmod -R +x /app/utilities/gdan-tmp-models/tools/ || true

# 8. Esposizione della porta per la dashboard Dash
EXPOSE 8060

# 9. Comando di avvio
CMD ["python", "main.py"]
