# Sturgeon CNS classifier (github.com/marcpaga/sturgeon @d86d20f). The model
# (general.zip) is a pipeline input.
FROM python:3.9-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends git procps \
    && rm -rf /var/lib/apt/lists/*
ARG STURGEON_COMMIT=d86d20f7120dc92cada9872e64ab2acaa2a9f046
RUN pip install --no-cache-dir numpy==1.26.4 pandas==2.3.2 matplotlib==3.5.1 \
        onnxruntime==1.12.1 pysam==0.19.0 modbampy==0.6.3 \
    && pip install --no-cache-dir "git+https://github.com/marcpaga/sturgeon@${STURGEON_COMMIT}"
ENV MPLBACKEND=Agg
