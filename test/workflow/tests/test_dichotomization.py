#!/usr/bin/env python3
from os.path import join, dirname

import pandas as pd

from smprofiler.workflow.common.dichotomization import Dichotomizer
from smprofiler.workflow.tabular_import.tabular_dataset_design \
    import TabularCellMetadataDesign
from smprofiler.workflow.dataset_designs.multiplexed_imaging.file_identifier_schema \
    import ELEMENTARY_PHENOTYPES_FILE_IDENTIFIER
from smprofiler.workflow.dataset_designs.multiplexed_imaging.file_identifier_schema \
    import get_input_filename_by_identifier


def test_thresholding():
    input_files_path = join(dirname(__file__), '..',
                            'data_compartments_explicit')
    file_manifest_file = join(input_files_path, 'file_manifest.tsv')
    dataset_design = TabularCellMetadataDesign(
        elementary_phenotypes_file=join(
            input_files_path,
            get_input_filename_by_identifier(
                ELEMENTARY_PHENOTYPES_FILE_IDENTIFIER,
                file_manifest_filename=file_manifest_file,
            ),
        ),
        compartments_file=join(
            input_files_path,
            get_input_filename_by_identifier(
                'Compartments file',
                file_manifest_filename=file_manifest_file,
            ),
        )
    )
    file_manifest = pd.read_csv(file_manifest_file, sep='\t')
    cell_manifest = TabularCellMetadataDesign.get_cell_manifest_descriptor()
    input_files = file_manifest[file_manifest['Data type']
                                == cell_manifest]['File name']
    for filename in input_files:
        cells = pd.read_csv(join(input_files_path, filename))
        rows = []
        for phenotype in dataset_design.get_elementary_phenotype_names():
            dataset_design.add_combined_intensity_column(cells, phenotype)
            feature = dataset_design.get_feature_name(phenotype)
            known_number_positives = sum(cells[feature])
            Dichotomizer.dichotomize(
                phenotype,
                cells,
                dataset_design=dataset_design,
                enable_overwrite_warning=False,
            )
            new_number_positives = sum(cells[feature])
            row = {
                'Phenotype': phenotype,
                'Previous': known_number_positives,
                'Thresholded': new_number_positives,
            }
            rows.append(row)
        print('')
        print(f'In file {filename}')
        print(pd.DataFrame(rows))


if __name__ == '__main__':
    test_thresholding()
