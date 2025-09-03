
from os.path import join
import re
from json import dumps as json_dumps

from smprofiler.standalone_utilities.float8 import SMALL_FLOAT_FORMAT
from smprofiler.standalone_utilities.float8 import generate_metadata_table

WRITE_ARTIFACTS = False
# WRITE_ARTIFACTS = True


def check_javascript_lookup() -> None:
    rows, df = generate_metadata_table(SMALL_FLOAT_FORMAT)
    def format_bin(integer: int):
        return bin(integer)[2:].rjust(8, '0')
    data = json_dumps(dict(map(lambda row: (format_bin(row.integer), row.decoded_value), rows)), indent=4)
    data = 'var lookup = ' + re.sub('"([01]+)"', r'0b\1' , data)
    filename = join('unit_tests', f'float_lookup_{SMALL_FLOAT_FORMAT.exponent_bits}_exponent_bits.js')
    if WRITE_ARTIFACTS:
        with open(filename, 'wt', encoding='utf-8') as file:
            file.write(data)
    else:
        with open(filename, 'rt', encoding='utf-8') as file:
            contents = file.read()
        assert contents == data


def thorough_check_table() -> None:
    _, df = generate_metadata_table(SMALL_FLOAT_FORMAT)
    filename = join('unit_tests', f'float_metadata_{SMALL_FLOAT_FORMAT.exponent_bits}_exponent_bits.txt')
    if WRITE_ARTIFACTS:
        with open(filename, 'wt', encoding='utf-8') as file:
            file.write(df.to_string(index=False))
    else:
        with open(filename, 'rt', encoding='utf-8') as file:
            contents = file.read()
        assert contents == df.to_string(index=False)


if __name__=='__main__':
    check_javascript_lookup()
    thorough_check_table()
