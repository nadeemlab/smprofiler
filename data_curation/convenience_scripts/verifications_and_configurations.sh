
function get_study_handle {
    dataset_subdirectory_handle="$1"
    base_directory="$2"
    python_command="
import json
with open('$base_directory/datasets/$dataset_subdirectory_handle/generated_artifacts/study.json', 'rt', encoding='utf-8') as file:
    print(json.loads(file.read())['Study name'])
"
    python -c "$python_command"
}

function check_exists_else_fail {
    echo -n "Checking for file $1 ... "
    if [[ ! -f $1 ]];
    then
        echo "does not exist."
        exit 1
    else
        echo "exists."
    fi
}

function handle_dbconfig_argument {
    dbconfig="$1"
    echo "Found database configuration file: $dbconfig" >&2
    echo $dbconfig
}

function check_for_smprofiler_availability {
    location=$(command -v smprofiler)
    if [[ "$location" == "" ]];
    then
        echo "smprofiler command is not available."
        exit 1
    fi
}

function create_run_directory {
    if [[ ! -d runs/ ]];
    then
        mkdir runs
        echo "Created runs/ ."
    fi
}

function get_available_dataset_handles_unsorted {
    handles=$(ls -1  datasets | grep -v 'template')
    for handle in $handles;
    do
        if [[ -f "datasets/$handle/generated_artifacts/file_manifest.tsv" ]];
        then
            echo "$handle "
        fi
    done
}

function get_available_dataset_handles {
    get_available_dataset_handles_unsorted | sort
}

function get_configured_run_handles_unsorted {
    if [[ ! -d runs ]];
    then
        return
    fi
    handles=$(ls -1 runs/)
    for handle in $handles;
    do
        if [[ -f "runs/$handle/import/run.sh" ]];
        then
            echo "$handle "
        fi
    done
}

function get_configured_run_handles {
    get_configured_run_handles_unsorted | sort | tr '\n' ' '
}

function get_run_directory {
    dataset="$1"
    basedirectory="$2"
    echo "$basedirectory/runs/$dataset/import"
}

function get_run_directory_parent {
    dataset="$1"
    basedirectory="$2"
    echo "$basedirectory/runs/$dataset"
}

function create_run_directories_for_datasets {
    datasets="$1"
    basedirectory=$2
    for dataset in $datasets; do
        create_run_directory_for_dataset $dataset $basedirectory
    done
}

function create_run_directory_for_dataset {
    dataset=$1
    basedirectory=$2
    parentdirectory=$(get_run_directory_parent $dataset $basedirectory)
    if [[ ! -d "$parentdirectory" ]];
    then
        echo "Creating run directory for '$dataset'."
        mkdir "$parentdirectory"
    fi
    rundirectory=$(get_run_directory $dataset $basedirectory)
    if [[ ! -d "$rundirectory" ]];
    then
        echo "Creating import run directory for '$dataset'."
        mkdir "$rundirectory"
    fi
}

function configure_run_directories_for_datasets {
    datasets="$1"
    basedirectory=$2
    for dataset in $datasets; do
        configure_run_directory_for_dataset $dataset $basedirectory
    done
}

function configure_run_directory_for_dataset {
    dataset=$1
    basedirectory=$2
    inputpath="$basedirectory/datasets/$dataset/generated_artifacts"
    if [[ ! -d "$inputpath" ]];
    then
        echo "Path $inputpath does not exist."
        exit 1
    fi
    rundirectory=$(get_run_directory $dataset $basedirectory)
    studyname=$(get_study_handle $dataset $basedirectory)

    cd $rundirectory
    echo "Configuring run in $rundirectory ."
    rm -f configure.sh run.sh nextflow.config main.nf workflow.config

    echo "[general]" >> workflow.config
    echo "db_config_file = $dbconfig" >> workflow.config
    echo "" >> workflow.config
    echo "[database visitor]" >> workflow.config
    echo "study_name = $studyname" >> workflow.config
    echo "" >> workflow.config
    echo "[tabular import]" >> workflow.config
    echo "input_path = $inputpath" >> workflow.config

    smprofiler workflow configure --workflow="tabular import" --config-file=workflow.config
    cd $basedirectory
}
