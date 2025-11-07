
SMPROFILER_FAST_POLLING=1 smprofiler workflow generate-analysis-report \
 "Melanoma intralesional IL2" \
 --database-config-file="../apiserver/.smprofiler_db.config.container" \
 --api-server="http://smprofiler-apiserver-testing-apiserver"

