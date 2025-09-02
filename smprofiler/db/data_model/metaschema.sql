CREATE TABLE study_lookup (
    study VARCHAR(512) PRIMARY KEY,
    schema_name VARCHAR(512)
);

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
