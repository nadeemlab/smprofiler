The scripts here are used to import dataset into a PostgreSQL database for the SMProfiler application or analysis, as well as organize or curate these datasets into a form acceptable for import.

1. [Curation or pre-processing](#curation-or-pre-processing)
2. [Doing import / upload into the database](#doing-import--upload-into-the-database)

# Curation or pre-processing

Datasets are stored in subdirectories of `datasets/`. To prepare a new dataset, follow the full example [here](`datasets/moldoveanu/README.md`). The example includes files pre-generated in a format ready for import into the database, but you can also re-generate them yourself.

Extraction scripts tend to be dataset-specific, but there are some common tasks like quantification over segments in images, and formulation of standardized representations of channel or clinical metadata.


# Doing import / upload into the database
The recommended import method is to use `smprofiler db interactive-uploader`.

It will take care of creating a run directory for Nextflow, configuring it with a `workflow.config`
file like:

```ini
[general]
db_config_file = /Users/username/.smprofiler_db.config.local

[database visitor]
study_name = Melanoma CyTOF ICI

[tabular import]
input_path = datasets/moldoveanu/generated_artifacts
```

or, in the case of S3 source files, with:

```ini
...
[tabular import]
input_path = s3://bucketname/moldoveanu
```

In the S3 case, you would have to make sure that credentials are available. Currently Nextflow requires, in the case of session-specific credentials, a "profile" in `~/.aws/credentials`, usually the profile named `default`.

> [!NOTE]
> To put the `generated_artifacts/` files into an S3 bucket, you can use: 
> ```sh
> aws s3 cp generated_artifacts s3://bucket-name/dataset-name --recursive`
> ```
