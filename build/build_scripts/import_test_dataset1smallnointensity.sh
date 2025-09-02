

cat build/build_scripts/.workflow.config | sed 's/YYY/3/g' > .workflow.config
smprofiler workflow configure --workflow='tabular import' --config-file=.workflow.config
nextflow run .

smprofiler graphs upload-importances --config_path=build/build_scripts/.graph.config --importances_csv_path=test/test_data/gnn_importances/3.csv

cat work/*/*/.command.log
smprofiler db status --database-config-file build/db/.smprofiler_db.config.local > table_counts.txt
smprofiler db count-cells --database-config-file=build/db/.smprofiler_db.config.local
diff build/build_scripts/expected_table_counts_1small.txt table_counts.txt
status=$?
[ $status -eq 0 ] && echo "Import created correct number of records." || echo "Import failed."
rm table_counts.txt

if [ $status -eq 0 ];
then
    exit 0
else
    exit 1
fi
