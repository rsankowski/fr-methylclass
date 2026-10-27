# samtools + bedtools + modkit 0.5.0 (pileup for crossNN / Sturgeon, probe intersect, read counts)
FROM mambaorg/micromamba:1.5.10-bookworm-slim
USER root
ENV PATH=/opt/conda/bin:$PATH
RUN micromamba install -y -n base -c conda-forge -c bioconda \
        samtools=1.21 bedtools=2.31.1 procps-ng curl \
    && micromamba clean -a -y
ARG MODKIT=0.5.0
RUN curl -fsSL https://github.com/nanoporetech/modkit/releases/download/v${MODKIT}/modkit_v${MODKIT}_u16_x86_64.tar.gz \
        | tar -xz -C /opt \
    && ln -s "$(find /opt -maxdepth 3 -type f -name modkit | head -n1)" /usr/local/bin/modkit \
    && modkit --version
USER $MAMBA_USER
