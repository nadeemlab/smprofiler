"""Do execution of a SQL statement and log the activity."""
from importlib.resources import as_file
from importlib.resources import files
from typing import Literal
import re

from smprofiler.db.database_connection import DBCursor
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)

VerbosityOptions = Literal['itemize', 'silent', None]


def _patch_schema(contents: str) -> str:
    buffer = contents
    line = r'quantitative_feature_value \(\n    identifier VARCHAR\(512\) PRIMARY KEY,'
    replacement = r'quantitative_feature_value (\n    identifier BIGSERIAL PRIMARY KEY,'
    buffer = re.sub(line, replacement, buffer)

    line = r'feature_specification \(\n    identifier VARCHAR\(512\) PRIMARY KEY,'
    replacement = r'feature_specification (\n    identifier BIGSERIAL PRIMARY KEY,'
    buffer = re.sub(line, replacement, buffer)

    line = r'VARCHAR\(512\) REFERENCES feature_specification\(identifier\)'
    replacement = r'INTEGER REFERENCES feature_specification(identifier)'
    buffer = re.sub(line, replacement, buffer)

    return buffer


def _retrieve_script(
    filename_description: tuple[str, str],
    contents: str | None,
    source_package: str | None,
    quiet: bool = False,
) -> str:
    filename, description = filename_description
    if description is None:
        description = filename
    if contents is None:
        if source_package is None:
            raise ValueError('Must supply package for source SQL file.')
        if not quiet:
            logger.info('Will execute %s.', description)
        with as_file(files(source_package).joinpath(filename)) as path:
            with open(path, encoding='utf-8') as file:
                script = file.read()
        if filename == 'schema.sql':
            script = _patch_schema(script)
    else:
        script = contents
    return script


def verbose_sql_execute(
    filename_description: tuple[str, str],
    database_config_file: str | None,
    contents: str | None = None,
    verbosity: VerbosityOptions = None,
    source_package: str | None = None,
    study: str | None = None,
):
    script = _retrieve_script(filename_description, contents, source_package)
    with DBCursor(database_config_file=database_config_file, study=study) as cursor:
        if not verbosity == 'silent' and verbosity != 'itemize':
            logger.debug(script)

        if verbosity == 'itemize':
            script_statements = [
                s + ';' for s in script.rstrip(' \n').split(';') if s != '']
            for statement in script_statements:
                logger.debug(statement)
                cursor.execute(statement)
        else:
            cursor.execute(script)
        cursor.close()
        logger.info('Done with %s.', filename_description[1])
