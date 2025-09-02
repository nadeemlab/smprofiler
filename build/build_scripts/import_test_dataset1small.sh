
FM=test/test_data/adi_preprocessed_tables/dataset1/file_manifest.tsv
cp $FM file_manifest.tsv.bak
(cat file_manifest.tsv.bak | grep -vE '(0_2|0_3|6_2|6_3|6_4)' | sed 's/Melanoma intralesional IL2/Melanoma intralesional IL2 collection: abc-123/g') > $FM
STUDY_JSON=test/test_data/adi_preprocessed_tables/dataset1/study.json
STUDY_SMALL_JSON=test/test_data/adi_preprocessed_tables/dataset1/study.small.json
cp $STUDY_JSON study.json.bak
cp $STUDY_SMALL_JSON $STUDY_JSON

cat build/build_scripts/.workflow.small.config | sed 's/YYY/1/g' > .workflow.config
smprofiler workflow configure --workflow='tabular import' --config-file=.workflow.config
nextflow run .

cp file_manifest.tsv.bak $FM
rm file_manifest.tsv.bak
cp study.json.bak $STUDY_JSON
rm study.json.bak

smprofiler graphs upload-importances --config_path=build/build_scripts/.graph.small.config --importances_csv_path test/test_data/gnn_importances/3.csv
smprofiler db count-cells --database-config-file=build/db/.smprofiler_db.config.local

cat work/*/*/.command.log
smprofiler db status --database-config-file build/db/.smprofiler_db.config.local > table_counts.txt
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
