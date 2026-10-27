# PDF report + CNV segment plot (matplotlib / pandas / pyyaml)
FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends procps \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir matplotlib==3.9.2 pandas==2.3.3 pyyaml==6.0.3
ENV MPLBACKEND=Agg
