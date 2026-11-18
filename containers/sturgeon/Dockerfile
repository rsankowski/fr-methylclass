# Sturgeon V2 CNS classifier (github.com/deRidderLab/sturgeon-v2 @d581abf) +
# modkit 0.5.0 and samtools for the per-read extract it reads. The model
# (cns-v2.5.zip) is a pipeline input.
FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends git curl procps samtools \
    && rm -rf /var/lib/apt/lists/*
ARG MODKIT=0.5.0
RUN curl -fsSL https://github.com/nanoporetech/modkit/releases/download/v${MODKIT}/modkit_v${MODKIT}_u16_x86_64.tar.gz \
        | tar -xz -C /opt \
    && ln -s "$(find /opt -maxdepth 3 -type f -name modkit | head -n1)" /usr/local/bin/modkit \
    && modkit --version
ARG STURGEON_V2_COMMIT=d581abfbe2388f6dd1fb1896a14b4c14deadf759
RUN pip install --no-cache-dir numpy==2.5.5 pandas==3.1.1 polars==2.1.0 pyyaml==6.0.3 \
        onnxruntime==1.32.0 tqdm==4.70.1 matplotlib==3.11.2 \
    && pip install --no-cache-dir "git+https://github.com/deRidderLab/sturgeon-v2@${STURGEON_V2_COMMIT}"
ENV MPLBACKEND=Agg
