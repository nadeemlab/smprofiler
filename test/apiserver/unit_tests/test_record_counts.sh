
function consider_exit() {
    if [[ "$1" != "0" ]];
    then
        exit 1
    fi
}

smprofiler db status --database-config-file .smprofiler_db.config.container > counts.txt; diff counts.txt unit_tests/record_counts1.txt
status=$?
rm counts.txt
[ $status -eq 0 ] && echo "Preloading of dataset 1 created correct combined number of records." || echo "Preloading of dataset 1 probably failed."
consider_exit $status
