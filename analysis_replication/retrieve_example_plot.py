import sys
import json
from os.path import exists
from os.path import join
from itertools import product
from subprocess import run
from cairo import SVGSurface
from cairo import Context

from pickle import dump
from pickle import load

from pandas import DataFrame
from PIL import Image
from numpy import power
from numpy import array

from smprofiler.db.feature_matrix_extractor import FeatureMatrixExtractor

PICKLED_FILENAME = 'dfs.pickle'
samples = ('Mold_sample_14RD', 'Mold_sample_22RD', 'Mold_sample_39RD', 'Mold_sample_41BL', 'Mold_sample_42RD')

def retrieve_dfs(database_config_file: str):
    cached = _retrieve_cached_dfs()
    if cached is not None:
        return cached
    extractor = FeatureMatrixExtractor(database_config_file=database_config_file)
    dfs = {sample: extractor.extract(specimen=sample)[sample].dataframe for sample in samples}
    cache_dfs(dfs)
    return dfs

def cache_dfs(dfs: dict[str, DataFrame]):
    with open(PICKLED_FILENAME, 'wb') as file:
        dump(dfs, file)
    print(f'Saved dataframes to {PICKLED_FILENAME} .')

def _retrieve_cached_dfs() -> dict[str, DataFrame] | None:
    if exists(PICKLED_FILENAME):
        print(f'Loading dataframes from {PICKLED_FILENAME} .')
        with open(PICKLED_FILENAME, 'rb') as file:
            return load(file)
    return None

def save_svg_circles(selectedcells, filename):
    with SVGSurface(filename, 1000, 1000) as surface: 
        context = Context(surface) 
        for _, row in selectedcells.iterrows():
            context.set_source_rgba(0.2, 0.2, 0.2, 0.2) 
            context.set_line_width(0.6)
            x = row['pixel x']
            y = row['pixel y']
            context.arc(x, y, 9, 0., 2 * 3.1415)
            context.stroke()

def create_svgs(dfs: dict[str, DataFrame]):
    selectedcells = {
        sample: {
            'Tc.ae': df[(df['C CD8A'] == 1) & (df['C CD3'] == 1) & (df['C CD45RO'] == 1) & (df['C CD20'] == 0)],
        }
        for sample, df in dfs.items()
    }
    for sample, pheno in product(selectedcells.keys(), ('Tc.ae',)):
        save_svg_circles(selectedcells[sample][pheno], f'{pheno}.{sample}.svg')

def get_tiff_filenames():
    if len(sys.argv) == 0:
        raise ValueError('Supply base directory for unzipped dataset, as command line argument.')
    base = sys.argv[1]
    if not exists(base):
        raise FileNotFoundError(f'Base directory you supplied {base} does not exist.')
    intermediate = 'CP_output_tiff'
    subdirectories = {
        'Mold_sample_14RD': '20190123_ICB_s1_p1_r1_a1_ac_14RD',
        'Mold_sample_22RD': '20190124_ICB_s1_p1_r11_a11_ac_22RD',
        'Mold_sample_39RD': '20190124_ICB_s1_p1_r1_a1_ac_39RD',
        'Mold_sample_41BL': '20190121_ICB_s1_p2_r4_a4_ac_41BL',
        'Mold_sample_42RD': '20190122_ICB_s1_p3_r3_a3_ac_42RD',
    }
    channel_filenames = {
        'CD3': 'CD3_Er170.tiff',
        'CD8': 'CD8a_Dy162.tiff',
        'CD45RO': 'CD45RO_Yb173.tiff',
        'SOX10': 'SOX10_Dy164.tiff',
    }
    tiff_files = {
        key: {
            channel: join(base, intermediate, subdirectory, channel_filename)
            for channel, channel_filename in channel_filenames.items()
        }
        for key, subdirectory in subdirectories.items()
    }
    print('Using TIFF files:')
    print(json.dumps(tiff_files, indent=4))
    return tiff_files

def get_colors():
    blue = (170, 150, 255)
    yellow = (235, 255, 17)
    green = (0, 225, 0)
    red = (170, 0, 0)
    colors_assigned = {'CD3': blue, 'CD8': yellow, 'CD45RO': green, 'SOX10': red}
    return {
        sample: colors_assigned
        for sample in samples
    }

def point_transform(value: float, channel: str | None = None, sample: str | None=None):
    m = 1.0
    if sample == 'Mold_sample_39RD' and channel=='SOX10':
        m = 0.6
    return min(power(m * value/30, 1.2), 255)

def create_composite(dfs, tiff_filenames):
    create_svgs(dfs)
    colors = get_colors()

    for sample, files in tiff_filenames.items():
        images = []
        for channel, file in files.items():
            im = Image.open(file)
            im = im.convert('RGB')
            r, g, b = im.split()
            R, G, B = colors[sample][channel]
            m = 1.0
            r = r.point(lambda i: point_transform(i * R * m, channel=channel, sample=sample))
            g = g.point(lambda i: point_transform(i * G * m, channel=channel, sample=sample))
            b = b.point(lambda i: point_transform(i * B * m, channel=channel, sample=sample))
            out = Image.merge('RGB', (r, g, b))
            print(f'{sample} {channel}')
            images.append(out)
        image0 = array(images[0])
        for image in images[1:]:
            image0 = image0 + array(image)
        i = Image.fromarray(image0)
        i.save(f'{sample}.png')

        pheno = 'Tc.ae'
        run(['convert', f'{pheno}.{sample}.svg', '-transparent', 'white', 'tmp.png']) 
        r, g, b, a = Image.open('tmp.png').convert("RGBA").split()
        a = a.point(lambda i: 0.8 * i)
        circles = Image.merge('RGBA', (r, g, b, a))
        i.paste(circles, (0, 0), mask=circles)
        i.save(f'{sample}.circles.png')

def get_args():
    if len(sys.argv) < 3:
        raise ValueError('Supply base directory for unzipped dataset and database config file, as command line arguments.')
    dataset_directory = sys.argv[1]
    database_config_file = sys.argv[2]
    if not exists(database_config_file):
        raise FileNotFoundError(f'Dataset directory you supplied {dataset_directory} does not exist.')
    if not exists(database_config_file):
        raise FileNotFoundError(f'Database config file you supplied {database_config_file} does not exist.')
    return dataset_directory, database_config_file

if __name__=='__main__':
    dataset_directory, database_config_file = get_args()
    dfs = retrieve_dfs(database_config_file)
    tiff_filenames = get_tiff_filenames()
    create_composite(dfs, tiff_filenames)

