"""CLI wrapper around CountRequester."""
import sys
import json

from smprofiler.db.database_connection import DBConnection
from smprofiler.apiserver.request_scheduling.ondemand_requester import OnDemandRequester


def get_counts(study_name, positives, negatives):
    connection = DBConnection()
    connection.__enter__()
    counts = OnDemandRequester.get_counts_by_specimen(connection, positives, negatives, study_name, ())
    connection.__exit__(None, None, None)
    return counts

def main():
    if sys.argv[1] == '1':
        counts = get_counts(
            'Melanoma intralesional IL2',
            ['CD3'], ['CD8', 'CD20'],
        )
    elif sys.argv[1] == '2':
        counts = get_counts(
            'Breast cancer IMC',
            ['CD3 epsilon'], ['CD20'],
        )
    else:
        raise ValueError(f'{sys.argv[1]} is not a valid case to test.')
    dump = counts.model_dump()
    json_str = json.dumps(dump, indent=4)
    print(json_str, end='')

if __name__ == '__main__':
    main()
