# MethyLYZR (github.com/marasteiger/MethyLYZR @f78855e), unmodified. Its MPG
# licence forbids redistribution and alterations: build this image locally,
# never push it. Model files are pipeline inputs.
FROM python:3.10-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends git samtools procps \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir arrow==1.3.0 matplotlib==3.8.2 natsort==8.4.0 numpy==1.26.3 \
        pandas==2.2.0 pyarrow==15.0.0 pysam==0.22.0
ARG METHYLYZR_COMMIT=f78855e6f00e77896aa7e9893ef4aa767f7bf212
RUN git clone https://github.com/marasteiger/MethyLYZR.git /opt/MethyLYZR \
    && git -C /opt/MethyLYZR checkout ${METHYLYZR_COMMIT} \
    && rm -rf /opt/MethyLYZR/.git /opt/MethyLYZR/data/ONT_15min_runs
ENV MPLBACKEND=Agg
