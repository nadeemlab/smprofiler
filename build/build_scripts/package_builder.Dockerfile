FROM ubuntu:24.04
ARG DEBIAN_FRONTEND=noninteractive
RUN apt update
RUN apt install software-properties-common -y
RUN apt-get install -y libpq-dev
RUN apt-get install -y build-essential libssl-dev
RUN add-apt-repository ppa:deadsnakes/ppa && apt update
RUN apt install python3.13 -y
RUN apt install python3.13-dev -y
RUN apt install python3.13-venv -y
ENV VIRTUAL_ENV=/opt/venv
RUN python3.13 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
ARG PIP_NO_CACHE_DIR=1
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python
RUN python -m pip install -U pip
ENV PATH="/root/.local/bin/:$PATH"
RUN python -m pip install build
RUN python -m pip install twine
CMD bash -c "echo 'available for commands'; while [ 0 -le 1 ]; do sleep 3600; echo 'sleep 3600... keep alive the container for availability for ongoing commands.'; done"

