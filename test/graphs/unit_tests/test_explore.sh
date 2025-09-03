smprofiler graphs explore-classes \
    --database-config-file ../graphs/.smprofiler_db.config.container \
    --study-name "Melanoma intralesional IL2"
status=$?
[ $status -eq 0 ] || echo "graphs explore-classes failed."

if [ $status -eq 0 ];
then
    exit 0
else
    exit 1
fi
