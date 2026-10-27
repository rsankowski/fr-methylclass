# dorado aligner 1.2.0 (keeps MM/ML modification tags) + samtools
FROM mambaorg/micromamba:1.5.10-bookworm-slim
USER root
ENV PATH=/opt/conda/bin:$PATH
RUN micromamba install -y -n base -c conda-forge -c bioconda samtools=1.21 procps-ng curl \
    && micromamba clean -a -y
ARG DORADO=1.2.0
RUN curl -fsSL https://cdn.oxfordnanoportal.com/software/analysis/dorado-${DORADO}-linux-x64.tar.gz \
        | tar -xz -C /opt \
    && ln -s /opt/dorado-${DORADO}-linux-x64/bin/dorado /usr/local/bin/dorado \
    && dorado --version
USER $MAMBA_USER
