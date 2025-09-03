"""Test that fast counts server can handle a request."""
import json
import sys

from smprofiler.db.database_connection import DBConnection
from smprofiler.apiserver.request_scheduling.ondemand_requester import OnDemandRequester


def main():
    study_name = 'Melanoma intralesional IL2'
    connection = DBConnection()
    connection.__enter__()
    counts = OnDemandRequester.get_counts_by_specimen(connection, ['CD3'], ['CD8', 'CD20'], study_name, ())
    connection.__exit__(None, None, None)

    counts_json = json.dumps(counts.model_dump(), indent=4).rstrip()
    with open('module_tests/expected_counts_structured1.json', 'rt', encoding='utf-8') as file:
        expected_counts_json = file.read().rstrip()
    if counts_json != expected_counts_json:
        print(f'Got counts: {counts_json}')
        sys.exit(1)


if __name__ == '__main__':
    main()
