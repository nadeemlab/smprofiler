CREATE TABLE study_lookup (
    study VARCHAR(512) PRIMARY KEY,
    schema_name VARCHAR(512)
);

-- Trained atlas-reference models (one row per trained (study, target_channel) model).
-- No foreign keys: chemical_species lives in each per-study schema (out of reach from
-- this shared metaschema), and a study may be trained before it is loaded into
-- study_lookup, so `study` and the channel names are stored as plain text. Multiple
-- rows per (study, target_channel) with distinct `created` values give model versions.
CREATE TABLE atlas_model (
    id SERIAL PRIMARY KEY,
    study VARCHAR(512),
    target_channel VARCHAR NOT NULL,
    input_channels VARCHAR[] NOT NULL,
    architecture_type VARCHAR NOT NULL,
    std_method VARCHAR NOT NULL,
    onnx_input_dtype VARCHAR NOT NULL,
    atlas_version VARCHAR,
    cv_r2 DOUBLE PRECISION,
    test_r2 DOUBLE PRECISION,
    test_mae DOUBLE PRECISION,
    n_train INTEGER,
    n_test INTEGER,
    training_time_seconds NUMERIC,
    size_bytes INTEGER,
    created TIMESTAMP WITH TIME ZONE DEFAULT now(),
    onnx_model BYTEA NOT NULL
);
CREATE INDEX atlas_model_study_target ON atlas_model (study, target_channel, created DESC);

CREATE TYPE findingstatus AS ENUM('pending_review','published','deferred_decision','rejected');
CREATE TABLE finding (
    id SERIAL PRIMARY KEY,
    study VARCHAR(512) REFERENCES study_lookup,
    submission_datetime TIMESTAMP,
    publication_datetime TIMESTAMP,
    status findingstatus,
    orcid_id VARCHAR,
    name VARCHAR,
    family_name VARCHAR,
    email VARCHAR,
    url VARCHAR,
    description VARCHAR,
    background VARCHAR,
    p_value DOUBLE PRECISION,
    effect_size DOUBLE PRECISION
);
