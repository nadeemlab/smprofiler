"""Convenience script for aggregating custom-logged time performance data."""
import argparse

try:
    from pandas import read_csv
    from pandas import concat
except ModuleNotFoundError as e:
    from smprofiler.standalone_utilities.module_load_error import \
        SuggestExtrasException
    SuggestExtrasException(e, 'workflow')
from pandas import read_csv  # pylint: disable=ungrouped-imports
from pandas import concat


def aggregate_performance_reports(reports):
    df = concat(reports).groupby(['from', 'to']).sum().reset_index()
    df['average time spent'] = df['total time spent'] / df['frequency']
    df['fraction'] = df['total time spent'] / sum(df['total time spent'])
    df.sort_values(by='fraction', inplace=True, ascending=False)
    return df


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        prog='smprofiler workflow merge-performance-reports',
        description='''
        Merges multiple computational performance reports (from each job) into one.
        '''
    )
    parser.add_argument(
        'performance_reports',
        nargs='+',
    )
    parser.add_argument(
        '--output',
        dest='output',
        type=str,
        required=True,
        help='Name of output file to be generated.',
    )
    args = parser.parse_args()

    performance_reports = [
        read_csv(file).drop(columns=['average time spent', 'fraction'])
        for file in args.performance_reports
    ]
    report = aggregate_performance_reports(performance_reports)
    with open(args.output, 'wt', encoding='utf-8') as file:
        file.write(report.to_markdown(index=False) + '\n')
