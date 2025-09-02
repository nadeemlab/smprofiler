"""Custom 8-bit floats."""

from math import log

from attr import define
from attr import fields as attrs_fields
from pandas import DataFrame  # type: ignore


@define
class SmallFloatByteFormat:
    """
    The specification for a custom floating-point format to fit inside exactly 1 byte, or 8 bits.

    The basic idea is to represent numbers of the form:
    
        (fixed part) * (base)^(exponent part)

    where the fixed part and the exponent part are encodeable as binary integers. The encoding that
    we actually do is not simply to make the fixed part and exponent part literally integers,
    because we want the floating-point scheme to have a favorable distribution. Specifically, we
    want:
    - range from 0 to 1
    - much higher density near 0

    The memory map is:

    - an `exponent_bits`-bit binary integer, E
    - a `fixed_bits`-bit binary integer, F

    The pair (E, F) then represents exactly the number given by the arithmetic formula:

        S * [ ((F / M)*(B-1) + 1)) * B^(E) - B^(0) ]

    where:
    - M is the integer upper bound for F, i.e. 2^(fixed_bits)
    - S is the constant scale factor that ensures that the largest value that occurs is 1
    - B is the specified base

    The term ((F / M) + 1) is a linear transformation of the F values, which range
    from 0 to M-1, onto the range 1 to 2. The purpose of this is to ensure that the fixed
    portion does not possibly contain duplicate information as the exponent portion, as in e.g.

        (3) * 2^4 = (6) * 2^3

    The term - B^(0) is an offset that ensures that byte 0 encodes 0 rather than the smallest
    denomination B^(0), which would otherwise be the smallest representable value.

    The `test` area has a table of extended metadata and a flat lookup table for the encoding of
    this type which we use as the default (exponent_bits = 3, fixed_bits = 5, base = 2)
    That area also has a script to generate distribution plots to compare the possible formats.
    """
    exponent_bits: int
    fixed_bits: int
    base: int
    max_fixed: int
    max_exponent: int
    lowest_denomination: float
    scale_adjustment: float


def float_format(exponent_bits: int, base: int) -> SmallFloatByteFormat:
    """Constructor for the SmallFloatByteFormat specification object."""
    if exponent_bits >= 8:
        raise ValueError(f'This format requires exactly 8 bits in memory map, and {exponent_bits} '
                          'exponent bits leave no room for the fixed portion.')
    if exponent_bits < 1:
        raise ValueError(f'This format requires at least 1 bit for encoding the exponent.')
    fixed_bits = 8 - exponent_bits
    Fmax = 2**fixed_bits - 1
    M = 2**fixed_bits
    highest = (1 + (Fmax / M)*(base - 1)) * base**(2**exponent_bits - 1) - base**(0)
    f = SmallFloatByteFormat(
        exponent_bits,
        fixed_bits,
        base,
        2**fixed_bits,
        2**exponent_bits,
        1,
        1.0 / highest,
    )
    return f


SMALL_FLOAT_FORMAT = float_format(3, 2)

class Float8OverflowError(OverflowError):
    is_underflow: bool

    def __init__(self, underflow: bool=False):
        self._is_underflow = underflow
        super().__init__()


def encode(value: float, f: SmallFloatByteFormat = SMALL_FLOAT_FORMAT) -> bytes:
    """
    Create an approximation of `value` in the 1-byte format specified by `f`.
    `value` should be non-negative and less than or equal to the largest `f`-representable number.
    The range is 0 to 1.0 in the case of the default, SMALL_FLOAT_FORMAT.
    """
    _value = (f.lowest_denomination + (value / f.scale_adjustment))
    if _value < 0:
        raise Float8OverflowError(underflow=True)
    exponent_integer = round(log(_value, f.base))
    nonexponent_part = _value / pow(f.base, exponent_integer)
    while nonexponent_part < 1:
        exponent_integer -= 1
        nonexponent_part = _value / pow(f.base, exponent_integer)
    exponent_stored = exponent_integer
    if exponent_stored >= f.max_exponent:
        raise Float8OverflowError()
    if exponent_stored < 0:
        raise Float8OverflowError(underflow=True)
    fixed = f.max_fixed * (nonexponent_part - 1) / (f.base - 1)
    fixed_stored = int(fixed)
    if fixed_stored >= f.max_fixed:
        raise Float8OverflowError()
    if fixed_stored < 0:
        raise Float8OverflowError(underflow=True)
    return ((exponent_stored << f.fixed_bits) + (fixed_stored)).to_bytes()


def decode(byte1: bytes, f: SmallFloatByteFormat = SMALL_FLOAT_FORMAT) -> float:
    """
    Expand the `f`-encoded float.
    """
    fixed = (int.from_bytes(byte1) % f.max_fixed / f.max_fixed) * (f.base - 1) + 1
    exponent = int.from_bytes(byte1) >> f.fixed_bits
    return (fixed * pow(f.base, exponent) - f.lowest_denomination) * f.scale_adjustment


@define
class SmallFloatMetadata:
    integer: int
    byte1: bytes
    decoded_value: float
    recoded: bytes
    recoded_integrity: bool
    expression: str
    exponent_integer: int
    fixed_integer: int


def _expand_metadata(s: SmallFloatMetadata) -> tuple:
    return tuple(map(
        lambda field: getattr(s, getattr(field, 'name')),
        attrs_fields(SmallFloatMetadata,
    )))


def _get_expression(byte1: bytes, f: SmallFloatByteFormat) -> str:
    fixed = (int.from_bytes(byte1) % f.max_fixed / f.max_fixed) + 1
    exponent = int.from_bytes(byte1) >> f.fixed_bits
    return f'(scale) * [{str(fixed).ljust(8)} * {f.base}^{exponent} - lowest value]'


def _get_fixed_integer(byte1: bytes, f: SmallFloatByteFormat) -> int:
    return int.from_bytes(byte1) % f.max_fixed


def _get_exponent_integer(byte1: bytes, f: SmallFloatByteFormat) -> int:
    return int.from_bytes(byte1) >> f.fixed_bits


def generate_metadata_table(f: SmallFloatByteFormat) -> tuple[list[SmallFloatMetadata], DataFrame]:
    rows: list[SmallFloatMetadata] = []
    for i in range(256):
        value = decode(i.to_bytes(), f=f)
        recoded = encode(value, f=f)
        s = SmallFloatMetadata(
            i,
            i.to_bytes(),
            value,
            recoded,
            recoded == i.to_bytes(),
            _get_expression(i.to_bytes(), f),
            _get_exponent_integer(i.to_bytes(), f),
            _get_fixed_integer(i.to_bytes(), f),
        )
        rows.append(s)
    rows = sorted(rows, key=lambda s: s.decoded_value)
    tuple_rows = [_expand_metadata(r) for r in rows]
    c = list(map(lambda field: getattr(field, 'name'), attrs_fields(SmallFloatMetadata)))
    df = DataFrame(tuple_rows, columns=c)
    return rows, df


def encode_float8_with_clipping(value) -> bytes:
    try:
        encoded = encode(value)
    except Float8OverflowError as error:
        if error._is_underflow:
            encoded = encode(0.0)
        else:
            encoded = encode(1.0)
    return encoded
