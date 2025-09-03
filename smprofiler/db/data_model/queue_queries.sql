-- Size of the "fresh" or active queue, jobs that have not been retried.
SELECT SUM(get_active_queue_size(schema_name)) AS total_active_queue_size FROM default_study_lookup.study_lookup ;

-- The fresh/active queue size broken down by dataset
SELECT schema_name, get_active_queue_size(schema_name) AS active_queue_size FROM default_study_lookup.study_lookup ;

-- Size of the whole queue, including retried and maximum-retried (failed) jobs.
SELECT SUM(get_queue_size(schema_name)) AS total_queue_size FROM default_study_lookup.study_lookup ;

-- The whole queue size, broken down by dataset.
SELECT schema_name, get_queue_size(schema_name) AS queue_size FROM default_study_lookup.study_lookup ;

-- The features still pending.
SELECT schema_name, get_pending_features(schema_name) AS pending_features FROM default_study_lookup.study_lookup ;
