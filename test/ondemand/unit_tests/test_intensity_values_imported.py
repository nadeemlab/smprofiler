"""Test presence of intensity values."""
import pandas as pd

from smprofiler.db.database_connection import DBCursor

def test_intensities():
    query = '''
    SELECT
        sdmp.specimen,
        eq.histological_structure,
        cs.symbol,
        eq.quantity,
        eq.discrete_value
    FROM expression_quantification eq
    JOIN chemical_species cs ON cs.identifier=eq.target
    JOIN histological_structure_identification hsi ON eq.histological_structure=hsi.histological_structure
    JOIN data_file df ON df.sha256_hash=hsi.data_source
    JOIN specimen_data_measurement_process sdmp ON df.source_generation_process = sdmp.identifier
    WHERE sdmp.specimen in (%s, %s, %s)
        AND cs.symbol in (%s, %s, %s, %s)
        AND eq.histological_structure in (%s, %s, %s, %s, %s)
    ORDER BY sdmp.specimen, eq.histological_structure, cs.symbol
    ;
    '''
    parameters = ('lesion 0_1', 'lesion 6_3', 'BaselTMA_SP43_3_X13Y6', 'CD27', 'MHCI', 'p53', 'EGFR', '89', '30', '524', '2909', '4442')

    rows = []
    studies = ['Melanoma intralesional IL2', 'Breast cancer IMC']
    for study in studies:
        with DBCursor(database_config_file='../ondemand/.smprofiler_db.config.container', study=study) as cursor:
            cursor.execute(query, parameters)
            rows.extend(cursor.fetchall())

    rows = [(r[0], r[1], r[2], float(r[3]), 1 if r[4] == 'positive' else 0) for r in rows]

    df = pd.read_csv('../test_data/adi_preprocessed_tables/dataset2/320.csv', sep=',')
    df2 = pd.read_csv('../test_data/adi_preprocessed_tables/dataset1/0.csv', sep=',')
    columns = {
        'EGFR': ['1021522Tm169Di EGFR Intensity', '1021522Tm169Di EGFR Positive'],
        'p53': ['207736Tb159Di p53 Intensity', '207736Tb159Di p53 Positive'],
        'CD27': ['CD27_Intensity', 'CD27_Positive'],
        'MHCI': ['MHCI_Intensity', 'MHCI_Positive'],
    }
    values = [
        list(df[columns['EGFR'][0]])[2],
        list(df[columns['EGFR'][1]])[2],
        list(df[columns['p53'][0]])[2],
        list(df[columns['p53'][1]])[2],
        list(df[columns['EGFR'][0]])[1535],
        list(df[columns['EGFR'][1]])[1535],
        list(df[columns['p53'][0]])[1535],
        list(df[columns['p53'][1]])[1535],
        list(df2[columns['CD27'][0]])[30],
        list(df2[columns['CD27'][1]])[30],
        list(df2[columns['MHCI'][0]])[30],
        list(df2[columns['MHCI'][1]])[30],
    ]

    cases = [
        ('BaselTMA_SP43_3_X13Y6', '2909', 'EGFR', values[0], values[1]),
        ('BaselTMA_SP43_3_X13Y6', '2909', 'p53', values[2], values[3]),
        ('BaselTMA_SP43_3_X13Y6', '4442', 'EGFR', values[4], values[5]),
        ('BaselTMA_SP43_3_X13Y6', '4442', 'p53', values[6], values[7]),
        ('lesion 0_1', '30', 'CD27', values[8], values[9]),
        ('lesion 0_1', '30', 'MHCI', values[10], values[11]),
        ('lesion 0_1', '89', 'CD27', 4.615379996154549, 0),
        ('lesion 0_1', '89', 'MHCI', 133.375, 1),
        ('lesion 6_3', '524', 'CD27', 2.43103, 0),
        ('lesion 6_3', '524', 'MHCI', 13.9828, 1),
    ]

    for case in cases:
        if not case in rows:
            message = f'Case not found: {case}'
            print(message)
            raise ValueError(message)

if __name__=='__main__':
    test_intensities()
