"""Test that the API server can handle certain edge cases for the query for counts."""
import json
from urllib.parse import quote
import subprocess

STUDY_NAME = quote('Melanoma intralesional IL2')
POSITIVE_MARKERS = ['CD3', 'CD4', 'CD8']
NEGATIVE_MARKERS: list[str] = ['']
ENDPOINTS = ('anonymous-phenotype-counts-fast', 'phenotype-counts')
HOST = 'smprofiler-apiserver-testing-apiserver'
PORT = 8080

def main():
    cases = [
        (HOST, PORT, ENDPOINTS[0], STUDY_NAME, POSITIVE_MARKERS, NEGATIVE_MARKERS, 7),
        (HOST, PORT, ENDPOINTS[0], STUDY_NAME, NEGATIVE_MARKERS, POSITIVE_MARKERS, 352),
        (HOST, PORT, ENDPOINTS[1], STUDY_NAME, POSITIVE_MARKERS, NEGATIVE_MARKERS, 7),
        (HOST, PORT, ENDPOINTS[1], STUDY_NAME, NEGATIVE_MARKERS, POSITIVE_MARKERS, 352),
    ]
    for host, port, endpoint, study_name, positive_markers, negative_markers, expected in cases:
        clause1 = '&'.join([f'positive_marker={m}' for m in positive_markers])
        clause2 = '&'.join([f'negative_marker={m}' for m in negative_markers])
        url = f'http://{host}:{port}/{endpoint}/?study={study_name}&'\
            f'{clause1}&'\
            f'{clause2}'

        if endpoint == ENDPOINTS[0]:
            result = subprocess.run(
                ['curl', '-s', url],
                capture_output=True,
                encoding='UTF-8',
                check=True,
            ).stdout
            response = json.loads(result)
        else:
            while True:
                result = subprocess.run(
                    ['curl', '-s', url],
                    capture_output=True,
                    encoding='UTF-8',
                    check=True,
                ).stdout
                response = json.loads(result)
                if not response['is_pending']:
                    break
        phenotype_total = sum(
            phenotype_count['count'] for phenotype_count in response['counts']
        )
        if phenotype_total != expected:
            raise ValueError(f'Got wrong number: {phenotype_total}, expected {expected}.')


if __name__=='__main__':
    main()
