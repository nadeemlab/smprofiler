
cat build/build_scripts/.workflow.config | sed 's/YYY/1/g' > .workflow.config
smprofiler workflow configure --workflow='tabular import' --config-file=.workflow.config
nextflow run .
cat work/*/*/.command.log

smprofiler graphs upload-importances --config_path=build/build_scripts/.graph.config --importances_csv_path=test/test_data/gnn_importances/1.csv
smprofiler graphs upload-importances --config_path=build/build_scripts/.graph_transformer.config --importances_csv_path=test/test_data/gnn_importances/1.csv

smprofiler db upload-sync-small --database-config-file=build/db/.smprofiler_db.config.local findings test/test_data/findings.json
smprofiler db upload-sync-small --database-config-file=build/db/.smprofiler_db.config.local gnn_plot_configurations test/test_data/gnn_plot.json
smprofiler db count-cells --database-config-file=build/db/.smprofiler_db.config.local

smprofiler db status --database-config-file build/db/.smprofiler_db.config.local > table_counts.txt
diff build/build_scripts/expected_table_counts.txt table_counts.txt
status=$?
[ $status -eq 0 ] && echo "Import created correct number of records." || (cat table_counts.txt && echo "Import failed.")
rm table_counts.txt

if [ $status -eq 0 ];
then
    exit 0
else
    exit 1
fi
