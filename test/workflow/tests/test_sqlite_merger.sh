
merged='example_merged.db'
if [[ -f $merged ]];
then
    rm $merged
fi
smprofiler workflow merge-sqlite-dbs data/example_db1.db data/example_db2.db --output=$merged
