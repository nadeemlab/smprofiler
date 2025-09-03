# Choose an appropriate base image
FROM python:3.11-slim-buster
WORKDIR /app

# Install apt packages you need here, and then clean up afterward
RUN apt-get update
# RUN apt-get install -y
RUN rm -rf /var/lib/apt/lists/*

# Install python packages you need here
ENV PIP_NO_CACHE_DIR=1
RUN pip install h5py==3.10.0
RUN pip install numpy==1.24.3
RUN pip install scipy==1.10.1

# Make the files you need in this directory available everywhere in the container
ADD . /app
RUN chmod +x train.py
RUN mv train.py /usr/local/bin/smprofiler-plugin-train-on-graphs
RUN chmod +x /app/print_graph_config.sh
RUN mv /app/print_graph_config.sh /usr/local/bin/smprofiler-plugin-print-graph-request-configuration
RUN chmod +x /app/print_training_config.sh
RUN mv /app/print_training_config.sh /usr/local/bin/smprofiler-plugin-print-training-configuration
