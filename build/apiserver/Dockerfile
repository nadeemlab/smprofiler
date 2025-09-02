FROM python:3.13-slim
ENV DEBIAN_FRONTEND=noninteractive
RUN apt update && apt install -y gcc libpq-dev curl && apt-get clean
RUN python3.13 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ADD https://astral.sh/uv/install.sh /uv-installer.sh
RUN sh /uv-installer.sh && rm /uv-installer.sh
ENV PATH="/root/.local/bin/:$PATH"
COPY pyproject.toml .
RUN bash -c 'source /opt/venv/bin/activate && uv pip install --extra apiserver -r pyproject.toml'
COPY requirements.txt /opt/venv/lib/python3.13/site-packages/smprofiler/apiserver/app/
COPY requirements.apiserver.txt .
RUN bash -c 'source /opt/venv/bin/activate && uv pip install -r requirements.apiserver.txt'
ARG version
ARG service_name
ARG WHEEL_FILENAME
LABEL version=$version
LABEL service_name=$service_name
COPY $WHEEL_FILENAME ./
RUN python -m pip install --no-deps "$WHEEL_FILENAME"
ENV API_SERVER_PORT=8080
HEALTHCHECK CMD curl --fail http://localhost:${API_SERVER_PORT}/ || exit 1
RUN TZ=America/New_York date +"%A %B %d %Y %l:%M %p %Z" >/build_datetime.txt
CMD echo "Container built at:" $(cat /build_datetime.txt) && uvicorn app.main:app --root-path /api --workers 6 --app-dir /opt/venv/lib/python3.13/site-packages/smprofiler/apiserver/ --host 0.0.0.0 --port ${API_SERVER_PORT} --log-level debug
