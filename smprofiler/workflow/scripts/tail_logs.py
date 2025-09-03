"""Convenience utility to follow logs during a nextflow workflow run."""
import argparse
from os import system

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        prog='smprofiler workflow tail-logs',
        description='Show and follow logs in a running workflow directory.'
    )
    args = parser.parse_args()
    system('tail -f -n1000 work/*/*/.command.log')
