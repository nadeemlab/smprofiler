# Use cuda.Dockerfile if you have a CUDA-enabled GPU
FROM python:3.11-slim-buster
WORKDIR /app

# Install apt packages you need here, and then clean up afterward
RUN apt-get update
RUN apt-get install -y \
    libhdf5-serial-dev \
    libatlas-base-dev \
    libblas-dev \
    liblapack-dev \
    gfortran \
    libpq-dev
RUN rm -rf /var/lib/apt/lists/*

# Install python packages you need here
ENV PIP_NO_CACHE_DIR=1
RUN pip install h5py==3.12.1
RUN pip install numpy==2.2.2
RUN pip install scipy==1.15.1
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install dgl -f https://data.dgl.ai/wheels/repo.html
RUN pip install dglgo -f https://data.dgl.ai/wheels-test/repo.html
ENV DGLBACKEND=pytorch
RUN pip install cg-gnn==0.3.2

# Make the files you need in this directory available everywhere in the container
ADD . /app
RUN chmod +x train.py
RUN mv train.py /usr/local/bin/smprofiler-plugin-train-on-graphs
RUN chmod +x /app/print_graph_config.sh
RUN mv /app/print_graph_config.sh /usr/local/bin/smprofiler-plugin-print-graph-request-configuration
RUN chmod +x /app/print_training_config.sh
RUN mv /app/print_training_config.sh /usr/local/bin/smprofiler-plugin-print-training-configuration
