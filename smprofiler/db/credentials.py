"""Structures and accessors for database credentials."""
from os import environ
import configparser

from attr import define

from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)

@define
class DBCredentials:
    """Data structure for database credentials."""
    endpoint: str
    database: str
    user: str
    password: str
    schema: str

    def update_schema(self, schema: str):
        self.schema = schema
        return self

def metaschema_schema() -> str:
    return 'default_study_lookup'

def main_database_name() -> str:
    return 'smprofiler_datasets'

def get_credentials_from_environment() -> DBCredentials:
    _handle_unavailability()
    return DBCredentials(
        environ['SINGLE_CELL_DATABASE_HOST'],
        main_database_name(),
        environ['SINGLE_CELL_DATABASE_USER'],
        environ['SINGLE_CELL_DATABASE_PASSWORD'],
        metaschema_schema(),
    )

class MissingKeysError(ValueError):
    def __init__(self, missing: set[str]):
        self.missing = missing
        message = f'Database configuration file is missing keys: {missing}'
        super().__init__(message)

def retrieve_credentials_from_file(database_config_file: str) -> DBCredentials:
    parser = configparser.ConfigParser()
    credentials = {}
    parser.read(database_config_file)
    if 'database-credentials' in parser.sections():
        for key in set(_get_credential_keys()).intersection(parser['database-credentials'].keys()):
            credentials[key] = parser['database-credentials'][key]
    missing = set(_get_credential_keys()).difference(credentials.keys())
    if len(missing) > 0:
        raise MissingKeysError(missing)
    return DBCredentials(
        credentials['endpoint'],
        main_database_name(),
        credentials['user'],
        credentials['password'],
        metaschema_schema(),
    )

def _handle_unavailability():
    variables = [
        'SINGLE_CELL_DATABASE_HOST',
        'SINGLE_CELL_DATABASE_USER',
        'SINGLE_CELL_DATABASE_PASSWORD',
    ]
    unfound = [v for v in variables if not v in environ]
    if len(unfound) > 0:
        raise EnvironmentError(f'Did not find in environment: {str(unfound)}')

def _get_credential_keys():
    return ['endpoint', 'user', 'password']
