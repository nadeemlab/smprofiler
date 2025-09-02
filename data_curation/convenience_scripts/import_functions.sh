
source convenience_scripts/verifications_and_configurations.sh

function get_dbname {
    dataset_subdirectory_handle="$1"
    base_directory="$2"
    handle=$(get_study_handle $dataset_subdirectory_handle $base_directory)
    lower=$(echo "$handle" | tr '[:upper:]' '[:lower:]')
    snake=$(echo "$lower" | tr ' ' '_')
    echo $snake
}

function get_dbconfig_argument {
    dbconfigargument="$1"
    dbconfig=$(handle_dbconfig_argument $dbconfigargument)
    echo $dbconfig
}

function compute_progress {
    run_directory="$1"
    prefix_size=$2
    manifests=$(cat $run_directory/work/*/*/.command.log | grep -o 'Number of cell manifest files: [0-9]\+' | grep -o '[0-9]\+' | tail -n1)
    completed=$(cat $run_directory/work/*/*/.command.log | grep -o 'Performance report [0-9]\+' | grep -o '[0-9]\+' | sort -n | tail -n1)
    if [[ "$completed" == "" ]]; then completed=0; fi;
    remaining=$(( $manifests - $completed ))
    width=$(( $(tput cols) - $prefix_size ))
    if (( $manifests > $width ));
    then
        _completed=$(echo "$completed * $width / $manifests" | bc)
        _remaining=$(echo "$remaining * $width / $manifests" | bc)
        manifests=$width
        completed=${_completed}
        remaining=${_remaining}
    fi
    progress1=$(printf "%0.s=" $(seq 1 $completed))
    if [[ "$remaining" != "0" ]];
    then
        progress2=$(printf "%0.s_" $(seq 1 $remaining))
    else
        progress2=""
    fi
    echo "$progress1$progress2"
}

function show_progress_of {
    lines=$#
    go_up="\033[F"
    for line in $(seq 1 $lines)
    do
        echo ''
    done
    while [[ true ]];
    do
        for line in $(seq 1 $lines)
        do
            printf "$go_up"
        done
        for line in $(seq 1 $lines)
        do
            dataset=${!line}
            run_directory=runs/$dataset/import
            echo -n "$dataset: "
            compute_progress $run_directory $(( ${#dataset} + 3 ))
        done
        sleep 4
    done
}

function show_progress {
    datasets=$(ls runs/)
    show_progress_of $datasets
}

function import_datasets {
    datasets="$1"
    basedirectory="$2"
    drop_first="$3"
    dbconfig="$4"
    for dataset in $datasets; do
        handle=$(get_study_handle $dataset $basedirectory)
        if [[ "$drop_first" == "yes" ]];
        then
            echo "Dropping "$handle"."
            smprofiler db drop --study-name="$handle" --database-config-file="$dbconfig"
        fi
        echo "Importing: $dataset ($handle)"
        import_dataset $dataset $basedirectory &
        sleep 2
    done
    wait
}

function import_dataset {
    dataset="$1"
    basedirectory="$2"
    rundirectory=$(get_run_directory $dataset $basedirectory)
    cd $rundirectory
    echo "Doing configured SMProfiler run (tabular import) in $rundirectory ."
    ./run.sh
    cd $basedirectory
}

function dump_metaschema_db {
    dbname=default_study_lookup
    formatted_date=$(printf '%(%Y_%m_%d)T\n' -1)
    pg_dump -h localhost -U postgres -Fc -O -x "$dbname" > $dbname.$formatted_date.sqldump
}

function dump_dataset {
    dataset_subdirectory_handle="$1"
    base_directory="$2"
    dbname=$(get_dbname $dataset_subdirectory_handle $base_directory)
    formatted_date=$(date +'%Y-%m-%d')
    pg_dump -h localhost -U postgres -Fc -O -x "$dbname" > $dbname.$formatted_date.sqldump
}

function dump_all_datasets {
    base_directory="$PWD"
    datasets=$(ls runs/)
    for dataset in $datasets;
    do
        dump_dataset $dataset $base_directory
    done
}

function restore_db {
    dbname="$1"
    filename="$2"
    database_config_file="$3"
    host=$(cat $database_config_file | grep 'endpoint' | sed 's/endpoint = //g')
    user=$(cat $database_config_file | grep 'user ' | sed 's/user = //g')
    password=$(cat $database_config_file | grep 'password ' | sed 's/password = //g')
    cmd="PGPASSWORD=$password pg_restore -v -x -O -C -c -j 4 -h $host -U $user -d postgres $filename"
    echo "Command is: $cmd"
    PGPASSWORD=$password pg_restore -v -x -O -C -j 4 -h $host -U $user -d postgres $filename
}

function extract_dbname {
    echo "$1" | grep -o '^[a-z_]\+'
}

function restore_all {
    database_config_file="$1"
    filenames=$(ls *.sqldump)
    for filename in $filenames
    do
        echo "Restoring $filename"
        dbname=$(extract_dbname $filename)
        restore_db $dbname $filename $database_config_file
    done
}
