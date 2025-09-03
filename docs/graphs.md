# How to train graph transformation models using SMProfiler

The intended procedure for using `smprofiler graphs` and graph workflows is:

1. [Prerequisites](#install-prerequisites)
2. [Explore the data available for a study and train the model](#explore-the-data-available-for-a-study-and-train-the-model)
3. [Configure a reproducible graph transformation workflow](#configure-a-reproducible-graph-transformation-workflow)
4. [Run the workflow](#run-the-workflow)

## Install prerequisites

Our graph transformation workflows are powered by [Nextflow](https://www.nextflow.io/docs/latest/getstarted.html) and [Docker](https://docs.docker.com/engine/install/) or [Singularity](https://docs.sylabs.io/guides/3.0/user-guide/installation.html), in addition to the SMProfiler Python package. Please ensure all three are installed before proceeding.
```sh
# Install Docker or Singularity per the links above
curl -s https://get.nextflow.io | bash
pip install smprofiler[workflow]
```

## Explore the data available for a study and train the model

- Evaluate the specimen cohorts at your disposal with `smprofiler graphs explore-classes`.
- Select sample strata to use and fetch graph data artifacts from the database using `smprofiler graphs extract`.
- Use an [SMProfiler plugin](https://github.com/nadeemlab/smprofiler-plugin) to transform your graph data into results, including cell-level importance scores.

## Configure a reproducible graph transformation workflow

To create artifacts that will reproducibly run through the entire process of gathering the data, transforming it, and reporting results in one line using Nextflow, we provide the `smprofiler workflow configure` utility. It uses the parameters obtained from the last step to create this reproducible workflow.

Currently, we a `graph plugin` workflow available in SMProfiler that makes available two first-class plugins supported by us SMProfiler developers, [`cg-gnn`](https://github.com/nadeemlab/smprofiler-cg-gnn) and [`graph-transformer`](https://github.com/nadeemlab/smprofiler-graph-transformer), with plans to add more in the future. Both train a deep learning model and return importance scores for cells used to train and test the model. If you'd like to develop your own, please refer to the [smprofiler-plugin repository](https://github.com/nadeemlab/smprofiler-plugin) for more information.

(Note that because most deep learning models like cg-gnn use non-deterministic algorithms, workflows may not be exactly reproducible.)

To set up a workflow, use the following command:
```
smprofiler workflow configure --workflow=<YOUR WORKFLOW> --config-file=<YOUR CONFIG FILE LOCATION>
```
For more information about how `smprofiler workflow configure` works, see
* [`smprofiler workflow configure -h`](smprofiler/workflow/scripts/configure.py)
* the template of the workflow configuration file, see [`.workflow.config.template`](smprofiler/workflow/assets/.workflow.config.template)

### The graph configuration file

[The template from the graphs submodule](smprofiler/graphs/template.config) is reproduced here for quick reference, but again please refer to the source code for the most up to date information. The values supplied here generally correspond to the default arguments (`study_name` and `strata` excepted) so you can omit them if you want to use the defaults.

```ini
[general]
db_config_file_path = smprofiler_db.config
study_name = Study name in SMProfiler database
random_seed = None

[extract]
strata = 1 2 3

[graph-generation]
validation_data_percent = 20
test_data_percent = 20
use_channels = true
use_phenotypes = true
roi_side_length = None
cells_per_roi_target = 10000
max_cells_to_consider = 100000
target_name = None
exclude_unlabeled = false
n_neighbors = 5
threshold = None

[cg-gnn]
in_ram = true
batch_size = 1
epochs = 5
learning_rate = 1e-3
k_folds = 0
explainer_model = pp
merge_rois = true

[graph-transformer]
task_name = GraphCAM
batch_size = 8
log_interval_local = 6

[upload-importances]
plugin_used = {cg-gnn or graph-transformer}
plugin_version = None
datetime_of_run = 2024-01-01 12:00:00
cohort_stratifier = None
```

Note that with this configuration file, parameters can't be eliminated to use the default value as is possible with CLI arguments.

General
* `db_config_file_path`: Do not change this. Inside the workflow, the database file in the workflow config's `db_config_file` is copied to the location specified in `db_config_file_path` and the workflow uses the copy internally, so any changes should be made upstream there.
* `study_name`: Same as `study-name` in the workflow configuration file.
* `random_seed`: Whether to use a random seed for reproducibility. If `None`, no random seed will be used.

Extract
* `strata`: Specimen strata to use as labels, identified according to the "stratum identifier" in `explore-classes`. This should be given as space separated integers. Can be set to `all` to use all strata.

Graph generation
* `validation_data_percent`: Percentage of data to use as validation data. Set to 0 if you want to do k-fold cross-validation. (Training percentage is implicit.)
* `test_data_percent`: Percentage of data to use as the test set. (Training percentage is implicit.)
* `use_channels`: If false, disable the use of individual channel information in the graph. (Only named phenotypes, a.k.a. ``composite phenotypes", would appear.)
* `use_phenotypes`: If false, disable the use of phenotype information in the graph. (Only individual channels would appear.)
* `roi_side_length`: Side length of the square region of interest (ROI) to use. If `None`, `cells_per_roi_target` overrules.
* `cells_per_roi_target`: Target number of cells per region of interest (ROI). Used with the median cell density across all slides to choose what (one) ROI size will be chosen for the study. (The actual number of cells per ROI will vary as cell density isn't uniform across slides.)
* `max_cells_to_consider`: Maximum number of cells to consider when building ROIs. If `None`, all cells will be considered.
* `target_name`: The name of a column in the dataframe whose true values indicate cells to be used when building ROIs. Can be set to `none` to use all cells in the sample.
* `exclude_unlabeled`: If true, exclude specimens with no label from graph generation.
* `n_neighbors`: Number of nearest neighboring cells to use when building the cell graph.
* `threshold`: Distance threshold to use when considering if two cells are neighbors. If `None`, no threshold will be used.

cg-gnn
* `in_ram`: If true, store the data in RAM.
* `batch_size`: Batch size to use during training.
* `epochs`: Number of training epochs to do.
* `learning_rate`: Learning rate to use during training.
* `k_folds`: Number of folds to use in cross validation. 0 means don't use k-fold cross validation unless no validation dataset is provided, in which case k defaults to 3.
* `explainer_model`: The explainer type to use. If not `none`, importance scores will be calculated using the model archetype chosen. `pp` is recommended.
* `merge_rois`: If true, return a CSV of importance scores merged together by sample.

graph-transformer
* `task_name`: The name of the task to use.
* `batch_size`: Batch size to use during training.
* `log_interval_local`: Interval at which to log local results.

Upload importances
* `plugin_used`: The plugin used to generate the importance scores. Must be `cg-gnn` or `graph-transformer`.
* `plugin_version`: The version of the plugin used to generate the importance scores, if available.
* `datetime_of_run`: The date (and time, if available) the plugin was run.
* `cohort_stratifier`: Name of the classification cohort variable the data was split on to create the data used to generate the importance scores, if available.

# Run the workflow

The workflow spins up a Docker container with the necessary dependencies to run the workflow, so we recommend installing it before trying to run it. Once `smprofiler workflow configure` finishes setting up, run the workflow with:

```sh
nextflow run .
```

If you're using Singularity, note that the Docker image to Singularity image conversion process can consume a lot of disk space. If you run into space issues, consider setting the [`SINGULARITY_TMPDIR`](https://docs.sylabs.io/guides/3.5/user-guide/appendix.html) environment variable to a directory on a drive with more space before running nextflow. We observed on our HPC that by default temporary files were stored in a `/tmp/` directory in a 12GB partition, which was insufficient for converting the Docker image. You can also set [`NXF_SINGULARITY_CACHEDIR`](https://github.com/nextflow-io/nextflow/issues/2685) to a directory with more space to store the converted Singularity images.
