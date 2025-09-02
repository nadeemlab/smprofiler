
function consider_exit() {
    if [[ "$1" != "0" ]];
    then
        exit 1
    fi
}

smprofiler db status --database-config-file .smprofiler_db.config.container > counts.txt; diff counts.txt module_tests/record_counts_1_2.txt
status=$?
rm counts.txt
[ $status -eq 0 ] && echo "Preloading of datasets 1 and 2 created correct combined number of records." || echo "Preloading of datasets 1 and 2 failed."
consider_exit $status
