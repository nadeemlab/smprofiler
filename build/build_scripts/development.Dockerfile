FROM nadeemlab-development/smprofiler-development-prereqs:latest
ARG WHEEL_FILENAME
ARG PIP_NO_CACHE_DIR=1
COPY pyproject.toml .
COPY smprofiler smprofiler
ENV SMProfiler_TESTING_MODE=1
RUN python -m build
RUN python -m pip install --no-deps "dist/$WHEEL_FILENAME"
