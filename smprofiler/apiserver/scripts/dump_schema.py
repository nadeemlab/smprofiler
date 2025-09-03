"""Dump OpenAPI schema to terminal."""
from json import dumps
from argparse import ArgumentParser
from argparse import RawDescriptionHelpFormatter


if __name__=='__main__':
    parser = ArgumentParser(
        prog='smprofiler apiserver dump-schema',
        description='Dump the OpenAPI schema (openapi.json) to the terminal.',
        formatter_class=RawDescriptionHelpFormatter,
    )
    parser.parse_args()
    from smprofiler.apiserver.app.main import app
    schema = app.openapi()
    print(dumps(schema, indent=2))
