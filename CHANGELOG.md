# v1.0.67
- First release of renamed package **smprofiler**.

# v1.0.66
- Adds a statistical subsample of all cells from a given dataset, for feasibility of low-resource downstream whole-study analysis. The new command is `spt db cache-subsample`, and the API exposes:
  - `cell-data-binary-intensity-whole-study-subsample`, a concatenation of metadata about the subsample (including default per-sample thresholds for each channel) and the intensities per-cell in a binary format.
  - `whole-study-subsample-metadata`, the metadata portion only.
  - `whole-study-subsample-binary`, the binary portion only.

# v1.0.50
- Adds a sample data cache to the ondemand service. The containers now prefer to take computation jobs for samples it has already downloaded and cached, vastly reducing the bandwidth burden on the database. The cache is limited/controlled with configurable environment variables `DATABASE_DOWNLOAD_CACHE_SAMPLE_LIMIT` and `DATABASE_DOWNLOAD_CACHE_LIMIT_MB`. When the cache limit in MB or the number of samples limit is exceeded, cached items are dropped in order of their (rounded, binned) size, and in the case of ties, oldest items first, until the limits are no longer exceeded.
- Vastly reduces the number of database connections made by both the ondemand and API services. Previously new connections were made frequently for simple isolated queries. Now a connection is maintained as long as possible and reused. This increased the rate of computation job queue clearance by about 10-fold compared to the prior implementation.

# v1.0.38
- Adds configurable `FEATURE_COMPUTATION_TIMEOUT_SECONDS` and `JOB_COMPUTATION_TIMEOUT_SECONDS`, with reasonable defaults. When feature computation is requested via the API, if computation time for all jobs exceed the given limit (for FEATUREs), null values are inserted for the remaining samples. Similarly for individual jobs, with respect to the job-specific timeout (for JOBs).

# v1.0.34
- Adds configurable `CELL_NUMBER_LIMIT_PROXIMITY` and `CELL_NUMBER_LIMIT_SQUIDPY` environment variables to application containers.

# v1.0.28
- Adds `ThresholdOptimizer` to improve automated gate/threshold adjustment for whole datasets.

# v1.0.23
- The `spt db review-submissions` CLI was updated to include delete functionality and to handle new `finding` table treatment.

# v1.0.16
- An error condition was fixed in which duplicate feature specifications could be inserted into the database when the same metric is requested multiple times simultaneously. Just adding a unique constraint wasn't feasible since the specifications are located in multiple tables, so an additional table was added (`feature_hash`) as a proxy for feature specification identity.

# v1.0.15
- Many updates were made to support the most recent versions of dependencies. This included PostgresQL 17.2 and Python 3.13, and a few dozen Python package dependencies.
- The development environment was heavily modified to make future dependency-related upates easier. We have separate pinned (`requirements.txt`) and unpinned (`pyproject.toml`) dependency declarations. Now, on every run of the integration test suite, the `requirements.txt` files are updated with the latest versions, so it will be easier to make such updates incrementally (i.e. with `git status` to see version changes). As the codebase is primarily to support an application and not a library, we do not have a real need to support older versions of anything.
- As part of the development environment updates, the Makefiles and Dockerfiles were simplified, and the for-testing Docker compose files are now creating environments that are more isolated from one another.
- We updated for `secure==1.0.1` and the headers were updated accordingly.
- We updated for `psycopg==3.2.5` by slightly altering our Postgres notifications processing.
- The computation task/job-queue code was refactored to separate pushing jobs (the concern of the API server) and popping jobs (the concern of the worker containers).
- ORM usage (`sqlmodel`, `alembic`), which was minimal, was deprecated.

# v1.0.10
- New `findings` API endpoint provides a mechanism for users to contribute precise findings with attribution.
- Adds `spt db review-submissions` to interactively make specific alterations to the contributions (e.g. to correct typos) and also to update visibility and review status.

# v1.0.8
- Adds `spt db load-testing` interactive script to stress test the application backend under varying conditions and report the performance results.

# v1.0.6
- Makes UMAP dimensional reduction more aggressive in removing discrete features before reduction.

# v1.0.5
- Adds a way to retrieve the version strings for a number of dependency packages.

# v1.0.4
- Refactors the assessment/recreation of derivative data payloads (e.g. binary feature matrices):
  - Deprecates unnecessary logic, since now a single study must be specified.
  - Assesses and recreates the different derivatives independently.

# v1.0.3
- Reduces the log burden due to computation worker processes, provides summaries instead.
- Adds more flexible triggering of job queue pops, on worker process start not just explicit signaling.
- Adds a robust timeout (default 5 minutes), after which any pending jobs will no longer have an effect when complete; incomplete computations are recorded as null and the queue is cleared of these items.

# v1.0.2
- Converts the database model to a single named database with one (PostgreSQL-sense) schema for each dataset.
- Uses the new model to implement cross-cut queries, specifically computation job count (load metric).
- Adds a TUI for dataset import to help prevent errors in selection of database credentials, data sources, and upload options.

# v1.0.0
- Includes comprehensive tutorial and reference documentation.
- Adds dataset "curation" or preprocessing details, with a complete example.
- A number of updates to the graph processing workflows.
- Improve UMAP functionality into an interactive plot.
- Fix some timing bugs in edge cases related to the feature value computation queue.
- Greatly improves handling of the Ripley statistic summaries.
- Adds support for S3 source files in Nextflow workflows that operate on these source files.

# v0.24.0
Implements a major refactoring of on-demand metrics computation in which each worker container picks up a single sample's worth of feature computation at a time. This is organized with a simple PostgresQL table considered as a task queue, and database notifications. Now all computations for a given sample begin from a database query for the same compressed binary payload representing phenotype and location data for all cells. The TCP client/server model for dispatching specific feature computations to different services is deprecated.

# v0.23.1
Implements a dataset collection concept using study name suffixes (tags/tokens/labels):
- The tabular import workflow uses value for key `Study collection` in `study.json`.
- API endpoint `study-names` hides collection-tagged datasets by default.
- Other API handlers unchanged, work as-is using the fully-qualified study names.
- `spt db collection ... --publish / --unpublish` provided to managed collection visibility.

# v0.17.5
Organize workflow configuration options into a workflow configuration file.
This breaks the API for tabular import and similar.

# v0.17.2
Add support for small specimens (small cell set) in GNN workflow.

# v0.17.1
Add KDTree optimization to GNN ROI creation.

# v0.16.2
- Deprecates heavy index on large tables:
  - Adds a new table for tracking scope ranges.
  - Converts the former `source_specimen` column on `expression_quantification` to a `SERIAL`` integer.
  - Makes tabular import keep track of ranges per-specimen in the new range_definitions table.
  - Updates the "optimized" sparse matrix query to use the ranges rather than the former huge index.
  - Deprecates the modify-constraints CLI entrypoint (only used internally now).
  - Deprecates the expression indexing module, CLI entrypoint, etc.

# v0.16.0
- Separates datasets into own databases:
  - `DBCursor` and `DBConnection` usage streamlined, typically requires study-scoping (dataset-scoping).
  - Deprecates `scstudies` database from database cluster. Replaced by `default_study_lookup` and per-dataset databases.
  - Update test data artifacts which depended on all datasets being cohoused in the same database (e.g. things dealing with identifiers issue )
  - Adds study-scoping throughout codebase where previously global identifers were assumed.
  - Updates development DB image from postgres 14.5 to 16.0.
  - Deprecates `initialize_schema.sql` that was previously used to feed the DB docker image initialization.
- Adds DGL and pytorch to the big development docker image (in which are run all the tests).
- Deprecate most occurrences of package-global namespace symbols, to reduce possible "leak" of unnecessary library imports for otherwise simple calls.

# v0.12.4
Deprecated nearest distance and density workflows.

# v0.12.3

Includes convenience whole-dataset pulling from the database.

# v0.12.2

* Deprecated front proximity workflow (for now).
* Large-scale linting of library code.

# v0.12.1

Separated build and test directories out of the source tree.
