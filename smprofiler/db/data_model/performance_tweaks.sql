
ALTER TABLE diagnosis
ADD UNIQUE (subject, condition, result, assessor, date) ;

ALTER TABLE histology_assessment_process
ADD UNIQUE (slide, assay, result, assessor, assessment_date) ;

ALTER TABLE cell_phenotype_criterion
ADD UNIQUE (cell_phenotype, marker, polarity, study) ;

ALTER TABLE feature_specifier
ADD UNIQUE (feature_specification, specifier, ordinality) ;

ALTER TABLE two_cohort_feature_association_test
ADD UNIQUE (selection_criterion_1, selection_criterion_2, test, p_value, feature_tested) ;

ALTER TABLE expression_quantification
ADD range_identifier_integer SERIAL ;

CREATE TABLE range_definitions (
    scope_identifier VARCHAR(512),
    tablename VARCHAR(512),
    lowest_value INT,
    highest_value INT
) ;

CREATE EXTENSION IF NOT EXISTS tablefunc;

CREATE TABLE sample_strata (
    stratum_identifier VARCHAR(512),
    sample VARCHAR(512),
    local_temporal_position_indicator VARCHAR(512),
    subject_diagnosed_condition VARCHAR(512),
    subject_diagnosed_result VARCHAR(512)
);

CREATE TABLE quantitative_feature_value_queue (
    feature INTEGER REFERENCES feature_specification(identifier),
    subject VARCHAR,
    computation_start TIMESTAMP WITH TIME ZONE,
    retries INTEGER
);

ALTER TABLE quantitative_feature_value_queue
ADD CONSTRAINT unique_qfvq UNIQUE (feature, subject) ;

ALTER TABLE quantitative_feature_value
ADD CONSTRAINT unique_qfv UNIQUE (feature, subject) ;

ALTER TABLE study_component
ADD CONSTRAINT unique_sc UNIQUE (primary_study, component_study) ;

CREATE TABLE feature_hash(
    feature SERIAL PRIMARY KEY,
    hash_identity VARCHAR UNIQUE
);

CREATE TABLE ondemand_studies_index (
    specimen VARCHAR(512),
    blob_type VARCHAR(512),
    blob_contents bytea
);

CREATE TABLE cell_set_cache (
    feature INTEGER,
    histological_structure VARCHAR(512)
);

CREATE OR REPLACE FUNCTION get_queue_size(_schemaname varchar, OUT result int)
  LANGUAGE plpgsql AS
$func$
BEGIN
  EXECUTE format('SELECT COUNT(*) as queue_size FROM %s.quantitative_feature_value_queue', _schemaname)
  INTO result;
END
$func$;

CREATE OR REPLACE FUNCTION get_active_queue_size(_schemaname varchar, OUT result int)
  LANGUAGE plpgsql AS
$func$
BEGIN
  EXECUTE format('SELECT COUNT(*) as active_queue_size FROM %s.quantitative_feature_value_queue WHERE retries=0', _schemaname)
  INTO result;
END
$func$;

CREATE OR REPLACE FUNCTION get_pending_features(_schemaname varchar)
  RETURNS TABLE(feature INT)
  LANGUAGE plpgsql AS
$func$
BEGIN
  RETURN QUERY
  EXECUTE format('SELECT DISTINCT feature FROM %s.quantitative_feature_value_queue', _schemaname)
  ;
END
$func$;
