"""Test that the API server can handle retrieving cells by importance and phenotype."""

from os.path import join
from json import loads
from json import dumps
from urllib.parse import quote
from subprocess import run

STUDY_NAME = quote('Melanoma intralesional IL2')
ENDPOINT = 'importance-composition'
HOST = 'smprofiler-apiserver-testing-apiserver'
PORT = 8080

POSITIVE_MARKERS = ['CD3', 'CD4', 'CD8']
NEGATIVE_MARKERS: list[str] = ['']
CELL_LIMIT = 50
PLUGIN = 'cg-gnn'
DATETIME_OF_RUN = '2023-10-02%2010:46%20AM'


def get_expected():
    filename = join('module_tests', 'expected_importance_fractions.json')
    with open(filename, 'rt', encoding='utf-8') as file:
        expected = loads(file.read())
    return expected


def main():
    cases = [
        (POSITIVE_MARKERS, NEGATIVE_MARKERS, PLUGIN, DATETIME_OF_RUN),
        (NEGATIVE_MARKERS, POSITIVE_MARKERS, None, None),
    ]

    for expected, (
        positive_markers,
        negative_markers,
        plugin,
        datetime_of_run,
    ) in zip(get_expected(), cases):
        clause0 = f'study={STUDY_NAME}'
        clause1 = '&'.join([f'positive_marker={m}' for m in positive_markers])
        clause2 = '&'.join([f'negative_marker={m}' for m in negative_markers])
        clause3 = f'&cell_limit={CELL_LIMIT}' if CELL_LIMIT else ''
        clause4 = f'&plugin={plugin}' if plugin else ''
        clause5 = f'&datetime_of_run={datetime_of_run}' if datetime_of_run else ''
        url = f'http://{HOST}:{PORT}/{ENDPOINT}/?{clause0}&{clause1}&{clause2}{clause3}{clause4}' \
            f'{clause5}'
        result = run(
            ['curl', '-s', url],
            capture_output=True,
            encoding='UTF-8',
            check=True,
        ).stdout
        response = loads(result)
        phenotype_total = sum(
            phenotype_count['count'] for phenotype_count in response['counts']
        )
        expected_total = sum(count for _, count in expected.items())
        for item in response['counts']:
            sample = item["specimen"]
            if item['count'] != expected[sample]:
                print(f'Expected {expected[sample]}, got {item["count"]}, for {sample}.')
                raise ValueError(f'Expected {expected[sample]}, got {item["count"]}, for {sample}.')
            print(f'Got expected {item["count"]} for {sample}.')
        if phenotype_total != expected_total:
            raise ValueError(f'Got wrong number: {phenotype_total}, expected {expected_total}.')


if __name__ == '__main__':
    main()
