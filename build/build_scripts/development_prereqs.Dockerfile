FROM ubuntu:24.04
ARG DEBIAN_FRONTEND=noninteractive
RUN apt update && apt-get install -y apt-transport-https && apt-get clean
RUN apt install software-properties-common -y && apt-get clean
RUN apt-get install -y libpq-dev && apt-get clean
RUN apt install openjdk-17-jdk -y && apt-get clean
RUN apt install xxd -y && apt-get clean
RUN apt install file -y && apt-get clean
RUN apt install -y bc && apt-get clean
RUN apt install gcc -y && apt-get clean
RUN apt install postgresql-client -y && apt-get clean
RUN apt-get install -y build-essential libssl-dev libffi-dev && apt-get clean
RUN apt-get install -y brotli && apt-get clean
RUN apt install curl -y
RUN curl -s https://get.nextflow.io | bash; mv nextflow /usr/local/bin/;
RUN bash -c 'if [[ "$(which nextflow)" = "" ]]; then echo "Nextflow not on path."; exit 1; fi;'
RUN apt install libgdal-dev -y && apt-get clean
RUN apt install -y texlive-latex-base texlive-fonts-recommended texlive-fonts-extra texlive-latex-extra
RUN add-apt-repository ppa:deadsnakes/ppa && apt update
RUN apt install python3.13 -y && apt-get clean
RUN apt install python3.13-dev -y && apt-get clean
RUN apt install python3.13-venv -y && apt-get clean
RUN apt install -y jq
ENV VIRTUAL_ENV=/opt/venv
RUN python3.13 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
ARG PIP_NO_CACHE_DIR=1
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python
RUN python -m pip install -U pip
ADD https://astral.sh/uv/install.sh /uv-installer.sh
RUN sh /uv-installer.sh && rm /uv-installer.sh
ENV PATH="/root/.local/bin/:$PATH"
COPY pyproject.toml .
RUN bash -c 'source /opt/venv/bin/activate && uv pip install --all-extras -r pyproject.toml'
COPY requirements.txt .
RUN python -m pip install setuptools>=82
RUN bash -c 'source /opt/venv/bin/activate && uv pip install -r requirements.txt'
RUN python -m pip install build
RUN python -m pip install twine
COPY README.md .
CMD bash -c "echo 'available for commands'; while [ 0 -le 1 ]; do sleep 3600; echo 'sleep 3600... keep alive the container for availability for ongoing commands.'; done"
