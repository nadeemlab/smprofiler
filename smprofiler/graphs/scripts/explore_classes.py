"""Report the different strata available to classify with."""

from argparse import ArgumentParser

from smprofiler.workflow.common.cli_arguments import add_argument


def parse_arguments():
    """Process command line arguments."""
    parser = ArgumentParser(
        prog='smprofiler graphs explore-classes',
        description="""See the strata available to classify on.

When preparing to perform graph neural network training on a new dataset, use:

```bash
smprofiler graphs explore-classes --database-config-file <config_file_location> --study-name <study_name>
```

This will print a list of classes that stratify the samples associated with this study. Note the
stratum identifiers for strata you want to use, if not all strata. They will be needed to perform
the data extraction process.

The database configuration file should have the following format, where `...` is replaced with the
relevant information to connect to your database instance:

```yaml
[database-credentials]
endpoint =  ...
user = ...
password = ...
```
"""
    )
    add_argument(parser, 'database config')
    add_argument(parser, 'study name')
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()

    from smprofiler.db.feature_matrix_extractor import FeatureMatrixExtractor
    extractor = FeatureMatrixExtractor(database_config_file=args.database_config_file)
    strata = extractor.extract_cohorts(study=args.study_name)['strata']
    print(strata.to_string())
