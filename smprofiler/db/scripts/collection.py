"""Utility to promote a dataset from a (private) collection to the general, public collection."""

import argparse

from smprofiler.db.database_connection import get_and_validate_database_config
from smprofiler.workflow.common.cli_arguments import add_argument
from smprofiler.db.publish_promote import PublisherPromoter


def parse_args():
    parser = argparse.ArgumentParser(
        prog='smprofiler db collection',
        description='Promote datasets from a private collection to the general, public collection, '
                    'or revert this action.',
    )
    add_argument(parser, 'database config')
    parser.add_argument(
        '--collection',
        dest='collection',
        help='The token/label for the study collection.',
        required=True,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        '--publish',
        action='store_true',
        default=False,
    )
    group.add_argument(
        '--unpublish',
        action='store_true',
        default=False,
    )
    return parser.parse_args()


def main():
    args = parse_args()
    database_config_file = get_and_validate_database_config(args)
    collection = args.collection
    promoter = PublisherPromoter(database_config_file)
    if args.publish:
        promoter.promote(collection)
    if args.unpublish:
        promoter.demote(collection)


if __name__=='__main__':
    main()
