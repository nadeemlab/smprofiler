
from urllib.parse import urlencode
from itertools import chain
from itertools import product
import re

from matplotlib import pyplot as plt
import seaborn as sns

import pandas as pd
from pandas import DataFrame
from pandas import concat
from pandas import pivot_table
from pandas import read_sql
pd.set_option('display.max_rows', 500)
pd.set_option('display.max_columns', 500)
pd.set_option('display.width', 1000)

from smprofiler.db.database_connection import DBCursor
from smprofiler.db.database_connection import DBConnection
from accessors import DataAccessor

def shorten_study(s: str) -> str:
    return s.split('collection: ')[0].rstrip()

def retrieve_source_data():
    _study = 'Bone marrow aging collection: e7dfa16f1ed64eddad2f19e46d21f8fede72aef9a30522bc46276aed35d23d19'
    access = DataAccessor(_study)

    splits = {
        'CDH1CDH3': ('CDH1', 'CDH3'),
        'KRT8KRT18': ('KRT8', 'KRT18'),
        'PanCK-SOX10': ('PanCK', 'SOX10'),
        'TCF1/7': ('TCF1', 'TCF7'),
    }

    s, _ = access._retrieve('study-names', '')
    studies = [item['handle'] for item in s]
    channels = {}
    for study in studies:
        query = urlencode([('study', study)])
        _channels, _ = access._retrieve('channels', query)
        print(study)
        print(', '.join(map(lambda item: item['symbol'], _channels)))
        print('')
        _channels = list(map(lambda item: item['symbol'], _channels))
        _channels = list(chain(*[splits[c] if c in splits else (c,) for c in _channels]))
        channels[study] = _channels
    
    all_channels = sorted(list(set(chain(*channels.values()))))
    print('\n'.join(all_channels))

    pseudo = list(filter(lambda c: re.search(r'_', c), all_channels))
    print('Pseudo channels omitted: ', end='')
    print(pseudo)
    all_channels = sorted(list(set(all_channels).difference(pseudo)))

    pseudo2 = ['intratumoral', 'stromal', 'Proerythroblast', 'Promyelocyte', 'Megakaryocyte', 'Myeloblasts', 'Autofluorescence', 'Endothelium']
    print('More pseudo channels omitted: ', end='')
    print(pseudo2)
    all_channels = sorted(list(set(all_channels).difference(pseudo2)))

    def gene_symbol_analysis(s: str) -> tuple[str, ...]:
        parts = re.findall(r'[a-zA-Z\-\.]+|[0-9]+', s)
        if ''.join(parts) != s:
            return (s.lower(), )
        else:
            def process(part: str) -> str | int:
                if re.match(r'^[0-9]+$', part):
                    return int(part)
                return part.lower()
            return tuple([process(part) for part in parts])

    all_channels = sorted(all_channels, key=gene_symbol_analysis)

    print(str(len(all_channels)) + ':')
    print('')
    print('\n'.join(all_channels))

    channel_details = None
    database_config_file = '.smprofiler_db.config'
    for study in studies:
        with DBConnection(database_config_file=database_config_file, study=study) as connection:
            # cursor.execute('SELECT * from chemical_species;')
            # rows = cursor.fetchall()
            df = read_sql('SELECT * from chemical_species cs JOIN biological_marking_system bms ON bms.target=cs.identifier;', connection)
        # df = DataFrame(rows)
        print(study)
        del df['study']
        del df['identifier']
        del df['target']
        del df['antibody']
        del df['chemical_structure_class']
        df['study'] = shorten_study(study)
        df = df[df['marking_mechanism'] != 'Computational identification using clustering']
        df = df[df['marking_mechanism'] != 'Manual annotation']
        print(df.to_string())
        print('')
        if channel_details is None:
            channel_details = df
        else:
            channel_details = concat([channel_details, df], axis=0)
    print(channel_details.sort_values(by='symbol').to_string())

    channel_details['ones'] = int(1)
    cd: DataFrame = pivot_table(channel_details, index='symbol', columns='study', values='ones', fill_value=int(0)).astype(int)
    cd['key'] = cd.apply(lambda row: (int(-1 * sum(row)), *row), axis=1)
    cd = cd.sort_values(by=['key', 'symbol'])
    cd_dup = cd[cd['key'].apply(lambda v: -1*v[0] > 1)]
    cd_single = cd[cd['key'].apply(lambda v: -1*v[0] == 1)]
    del cd['key']
    del cd_dup['key']
    del cd_single['key']
    print(cd.to_string())
    plt.figure(figsize=(2, 7), layout="constrained")
    # ax = sns.heatmap(cd, cmap='OrRd', linewidth=0.5, xticklabels=True, yticklabels=True, cbar=False)
    ax = sns.heatmap(cd_dup, cmap='OrRd', linewidth=0.5, xticklabels=True, yticklabels=True, cbar=False)
    plt.subplots_adjust(left=0.2, top=0.15, bottom=0.15, right=0.2)
    ax.tick_params(labelsize=5)
    ax.tick_params(axis='x', top=False, labeltop=True, bottom=False, labelbottom=False, labelrotation=90)
    ax.tick_params(axis='y', left=False)
    ax.set_xlabel('')
    ax.set_ylabel('')
    plt.savefig('channels_measured_in_studies.svg')

    print(cd_dup.to_string())
    print(cd_single.to_string())
    cd_single = cd_single.reset_index()
    specialized = cd_single.melt(id_vars=['symbol'], value_vars=cd_single.columns)
    specialized = specialized[specialized['value'] != 0]
    del specialized['value']
    print(specialized.to_string())
    singletons = {}
    for _study, group in specialized.groupby('study'):
        cs = group['symbol']
        print(cs)
        cs = sorted(list(cs), key=gene_symbol_analysis)
        singletons[_study] = cs
        print(_study)
        print(cs)
    m = max(len(cs) for cs in singletons.values())
    for _study in singletons:
        l = len(singletons[_study])
        singletons[_study] = singletons[_study] + ['']*(m-l)
    print(singletons)
    df = DataFrame(singletons)
    print(df.to_string())
    
    plt.show()

    # return


    # P1 = {'positive_markers': ['CD4'], 'negative_markers': []}
    # P2 = {'positive_markers': ['CD3', 'intratumoral'], 'negative_markers': []}
    # df = access.counts([P1, P2])
    # print(df.to_string())

    df = access.feature_matrix('WCM10')
    # df = access.feature_matrix('UMAP virtual sample')
    print(df.shape)

    print(df.columns)
    channels = ['CD71', 'CD61', 'CD117', 'CD38', 'CD34', 'CD15']
    df2 = df.melt(channels, var_name='Cell type', value_name='Dummy')
    df3 = df2[df2['Dummy'] > 0][channels + ['Cell type']]
    print(df3)

    mono = ['Mast_cells', 'B_cell_precursor', 'Hematopoietic_stem_and_progenitor_cells', 'Plasma_cells']
    df4 = df3[df3['Cell type'].apply(lambda x: x in mono)]

    # g = sns.jointplot(data=df, x="CD34", y="CD38", hue='Hematopoietic_stem_and_progenitor_cells')
    # g = sns.pairplot(data=df3, hue='Cell type')
    g = sns.pairplot(data=df4, hue='Cell type', plot_kws={'s': 1})

    plt.savefig('pairwise.svg')
    plt.show()


if __name__=='__main__':
    retrieve_source_data()
