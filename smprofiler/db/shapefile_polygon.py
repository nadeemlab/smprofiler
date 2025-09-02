"""Extract the sequences of points of a polygon from a Shapefile."""
import base64
import mmap
import shapefile  # type: ignore


def extract_points(shapefile_base64_ascii):
    bytes_original = base64.b64decode(shapefile_base64_ascii.encode('utf-8'))
    memmap = mmap.mmap(-1, len(bytes_original))
    memmap.write(bytes_original)
    memmap.seek(0)
    reader = shapefile.Reader(shp=memmap)
    shape_type = reader.shape(0).shapeType
    shape_type_name = reader.shape(0).shapeTypeName
    if shape_type != 5:
        raise ValueError(
            'Expected shape type index is 5 (according to page 4 of ESRI specification), '
            f'not {shape_type}.')
    if shape_type_name != 'POLYGON':
        raise ValueError(f'Expected shape type is "POLYGON", not {shape_type_name}.')
    return reader.shape(0).points
