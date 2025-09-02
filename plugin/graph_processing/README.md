# Graph processing

These plugins create and process cell graphs that are used to train prediction models and extract features from the models.

New plugins can be contributed by modifying the [template](template/) or implementation ([cg-gnn](cg-gnn/), [graph-transformer](graph-transformer/)) source to use alternative processing methods.

Graph processing plugins are Docker images. (template [Dockerfile](template/Dockerfile), `cg-gnn` [Dockerfile](../../build/plugins/graph_processing/cg-gnn.dockerfile) and `graph-transformer` [Dockerfile](../../build/plugins/graph_processing/graph-transformer.dockerfile))

Each plugin is expected to have the following commands available on the path:
* `smprofiler-plugin-print-graph-request-configuration`, which prints to `stdout` the configuration file intended to be used by this plugin to fetch graphs from an SMProfiler instance to use for model training. An empty configuration file and a shell script to do this is provided in the template, as well as the command needed to make this available in the template `Dockerfile`.
* `smprofiler-plugin-train-on-graphs` trains the model and outputs a CSV of importance scores that can be read by `smprofiler graphs upload-importances`. A template [`train.py`](template/train.py) is provided that uses a command line interface specified in `train_cli.py`. Its arguments are
    1. `--input_directory`, the path to the directory containing the graphs to train on.
    2. `--config_file`, the path to the configuration file. This should be optional, and if not provided `smprofiler-plugin-train-on-graphs` should use reasonable defaults.
    3. `--output_directory`, the path to the directory in which to save the trained model, importance scores, and any other artifacts deemed important enough to save, like performance reports.
* `smprofiler-plugin-print-training-configuration`, which prints to `stdout` an example configuration file for running `smprofiler-plugin-train-on-graphs`, populated either with example values or the reasonable defaults used by the command. An empty configuration file and a shell script to do this is provided in the templatere, as well as the command needed to make this available in the template `Dockerfile`.
