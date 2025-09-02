
function nf_clean() {
    rm -rf work/
    rm -rf results/
    rm -rf .nextflow/
    rm -f .nextflow.config
    rm -f .nextflow.log
    rm -f .nextflow.log.*
    rm -f main.nf
}

function consider_exit() {
    if [[ "$1" != "0" ]];
    then
        exit 1
    fi
}

cat build/build_scripts/.workflow.config | sed 's/YYY/1/g' > .workflow.config
smprofiler workflow configure --workflow='tabular import' --config-file=.workflow.config
nextflow run .
cat work/*/*/.command.log

nf_clean

cat build/build_scripts/.workflow.config | sed 's/YYY/2/g' > .workflow.config
smprofiler workflow configure --workflow='tabular import' --config-file=.workflow.config
nextflow run .
cat work/*/*/.command.log

smprofiler db count-cells --database-config-file=build/db/.smprofiler_db.config.local
nf_clean

smprofiler db status --database-config-file build/db/.smprofiler_db.config.local > counts.txt
cat counts.txt
diff counts.txt build/build_scripts/expected_counts_1and2.txt
status=$?
rm counts.txt
consider_exit $status
