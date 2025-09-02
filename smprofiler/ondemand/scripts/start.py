"""Entry point into the computation worker service."""

from argparse import ArgumentParser
from argparse import RawDescriptionHelpFormatter

from smprofiler.db.database_connection import wait_for_database_ready

from smprofiler.ondemand.worker import OnDemandWorker
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger('smprofiler ondemand start')


if __name__ == '__main__':
    parser = ArgumentParser(
        prog='smprofiler ondemand start',
        description='Start a worker to do computation jobs.',
        formatter_class=RawDescriptionHelpFormatter,
    )
    parser.parse_args()
    wait_for_database_ready(verbose=False)
    worker = OnDemandWorker()
    worker.start()
