SINGLE_CELL_DATABASE_HOST=smprofiler-db---testing-only-apiserver SINGLE_CELL_DATABASE_USER=postgres SINGLE_CELL_DATABASE_PASSWORD=postgres SMPROFILER_FAST_POLLING=1 smprofiler workflow generate-analysis-report \
 "Melanoma intralesional IL2" \
 --database-config-file="../apiserver/.smprofiler_db.config.container" \
 --api-server="http://smprofiler-apiserver-testing-apiserver" \
 --omitted-cohorts=2,4

