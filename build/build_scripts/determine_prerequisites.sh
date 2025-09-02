#!/bin/bash
# Uses uv to quickly determine pinned package versions for an installation
# of the source package with given extras module.
# Example:
#
#     ./determine_prerequisites.sh [apiserver] requirements.apiserver.txt

PYTHON=python3.13

MODULE="$1"
FILENAME="$2"
if [[ "$FILENAME" == "" ]]; then
    exit 1
fi

SPECIFIER=$(echo $FILENAME | sed 's/\./_/g' | sed 's/_txt//g');

function handle_status() {
    status=$1
    if [ $1 -gt 0 ]; then
        exit $1
    fi
}

$PYTHON -m venv .venv_$SPECIFIER;
source .venv_$SPECIFIER/bin/activate
uv pip install .$MODULE
handle_status $?
if [ $? -gt 0 ]; then
    exit 1
fi
uv pip freeze | grep -v smprofiler > $FILENAME
handle_status $?
deactivate
rm -rf .venv_$SPECIFIER
