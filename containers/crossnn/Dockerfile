# crossNN NN classifier (gitlab.com/euskirchen-lab/crossnn @26e4db9).
# Only NN_model.py is needed; the models (git-lfs) are pipeline inputs.
# Versions = the environment the GUI runs crossNN in (CPU build of torch).
FROM python:3.10-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends git git-lfs procps \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu torch==2.10.0+cpu \
    && pip install --no-cache-dir numpy==2.2.6 pandas==2.3.3 scikit-learn==1.6.1
ARG CROSSNN_COMMIT=26e4db9bf9c16711aa834f2e944a84a920baccc7
RUN GIT_LFS_SKIP_SMUDGE=1 git clone https://gitlab.com/euskirchen-lab/crossnn.git /opt/crossNN \
    && git -C /opt/crossNN checkout ${CROSSNN_COMMIT} \
    && rm -rf /opt/crossNN/.git /opt/crossNN/models
ENV PYTHONPATH=/opt/crossNN
