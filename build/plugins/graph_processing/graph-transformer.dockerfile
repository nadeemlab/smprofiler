FROM pytorch/pytorch:2.1.2-cuda11.8-cudnn8-runtime
WORKDIR /app

# Install apt packages you need here, and then clean up afterward
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    libhdf5-dev \
    libopenblas0 libopenblas-dev \
    libprotobuf-dev \
    libjpeg8-dev \
    libpng-dev \
    libtiff-dev \
    libwebp-dev \
    libopenjp2-7-dev \
    libtbb-dev \
    libeigen3-dev \
    tesseract-ocr tesseract-ocr-por libtesseract-dev && \
    rm -rf /var/lib/apt/lists/*

# Install python packages you need here
ENV PIP_NO_CACHE_DIR=1
RUN pip install h5py==3.12.1
RUN pip install numpy==2.2.2
RUN pip install scipy==1.15.1
RUN pip install pandas
RUN pip install pillow
RUN pip install tensorboardX
RUN pip install opencv-python
RUN pip install einops
RUN pip install torch-geometric

# Make the files you need in this directory available everywhere in the container
ADD . /app
RUN chmod +x train.py
RUN mv train.py /usr/local/bin/smprofiler-plugin-train-on-graphs
RUN chmod +x /app/print_graph_config.sh
RUN mv /app/print_graph_config.sh /usr/local/bin/smprofiler-plugin-print-graph-request-configuration
RUN chmod +x /app/print_training_config.sh
RUN mv /app/print_training_config.sh /usr/local/bin/smprofiler-plugin-print-training-configuration
