# Lamprey haematological-malignancy classifier (github.com/princessmaximacenter/Lamprey
# @e885837) + modkit 0.5.0 for lamprey-preprocess. The 6.8 GB model snapshot is
# a pipeline input (or a HuggingFace repo id fetched at run time).
FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends git curl procps \
    && rm -rf /var/lib/apt/lists/*
ARG MODKIT=0.5.0
RUN curl -fsSL https://github.com/nanoporetech/modkit/releases/download/v${MODKIT}/modkit_v${MODKIT}_u16_x86_64.tar.gz \
        | tar -xz -C /opt \
    && ln -s "$(find /opt -maxdepth 3 -type f -name modkit | head -n1)" /usr/local/bin/modkit \
    && modkit --version
ARG LAMPREY_COMMIT=e8858375e539032dfeb8057d1b97322752af798f
RUN pip install --no-cache-dir numpy==2.5.3 pandas==3.0.5 polars==1.44.2 pyyaml==6.0.3 \
        onnxruntime==1.30.0 huggingface_hub==1.31.0 matplotlib==3.11.2 \
    && pip install --no-cache-dir "git+https://github.com/princessmaximacenter/Lamprey@${LAMPREY_COMMIT}"
ENV MPLBACKEND=Agg
