#!/bin/bash

source convenience_scripts/verifications_and_configurations.sh

dbconfigargument="$1"
dbconfig=$(handle_dbconfig_argument $dbconfigargument)

check_exists_else_fail "$dbconfig"
check_for_smprofiler_availability
create_run_directory

one_inclusion="$2"
if [[ "$one_inclusion" == "" ]];
then
    one_inclusion="ALL_DATASET_DIRECTORY_HANDLES"
fi

SECONDS=0
if [[ "$one_inclusion" == "ALL_DATASET_DIRECTORY_HANDLES" ]];
then
    datasets=$(get_available_dataset_handles)
else
    datasets=$(get_available_dataset_handles | grep -o "$one_inclusion")
fi
create_run_directories_for_datasets "$datasets" $PWD
configure_run_directories_for_datasets "$datasets" $PWD

echo "Run directory structure:"
tree -L 3 runs/
echo ""

echo "Configuration took $SECONDS seconds ("$(( SECONDS / 60 ))" minutes)."
