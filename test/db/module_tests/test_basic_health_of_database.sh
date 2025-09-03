
smprofiler db status --database-config-file .smprofiler_db.config.container >/dev/null 2>&1
result_code="$?"
if [ $result_code -gt 0 ];
then
    echo "Basic health check of database failed."
    exit 1
else
    exit 0
fi
