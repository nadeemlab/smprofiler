"""Test that the binary manipulation operations are compatible."""

from numpy import asarray
from numpy.typing import NDArray

from smprofiler.workflow.common.sparse_matrix_puller import SparseMatrixPuller
from smprofiler.ondemand.computers.squidpy_computer import extract_binary

def primitive_compress(vector: tuple[int, ...]) -> int:
    return sum(map(lambda pair: pair[1]*int(pow(2, pair[0])), enumerate(vector)))


def _test_roundtrip_vector(vector: tuple[int, ...]) -> None:
    length = len(vector)
    vector2 = extract_binary(primitive_compress(vector), length)
    if not vector2 == vector:
        raise ValueError(f'Expected equal:\n{vector}\n{vector2}')


def _test_roundtrip_array(array: NDArray) -> None:
    compress = SparseMatrixPuller._compress_bitwise_to_int
    length = len(array)
    assert (asarray(extract_binary(compress(array), length)) == array).all()


def _test_roundtrip_int(integer: int) -> None:
    compress = SparseMatrixPuller._compress_bitwise_to_int
    lengths = (32, 64, 128, 101)
    for length in lengths:
        assert compress(asarray(extract_binary(integer, length))) == integer


def test_binary_equivalence() -> None:
    vectors =  ((0, 1, 0, 0), (0, 0, 0, 0, 0), (0, 1, 0, 0, 1, 1), (0, 1, 0, 1, 1, 0, 1, 1, 1, 0))
    ints = (0, 1, 7, 139, 800012, 128827052)
    for vector in vectors:
        array = asarray(vector)
        _test_roundtrip_vector(vector)
        _test_roundtrip_array(array)
    for integer in ints:
        _test_roundtrip_int(integer)


if __name__=='__main__':
    test_binary_equivalence()
