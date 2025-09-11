
import re
from math import log10
import seaborn as sns
from matplotlib import pyplot as plt

from survey import get_default_host
from survey import survey

host = get_default_host(None)
study = open('study.txt', 'rt', encoding='utf-8').read().rstrip()
df = survey(host=host, study=study, interactive=True)
df['qual'] = df['multiplier'] * df['p'].apply(log10)

dfm = df[df['metric'] == 'proximity']
dfm['-log10(p)'] = dfm['p'].apply(log10) * -1
def map_names(c: str) -> str:
    m = {
        '1': '>60 y.o.',
        '2': '20-60 y.o.',
        '3': '<20 y.o.',
    }
    return m[c]
dfm['elevated in cohort'] = dfm['higher_cohort'].apply(map_names)

fig, ax = plt.subplots(1, 1, figsize=(7, 7))
sns.scatterplot(data=dfm, x='multiplier', y='-log10(p)', hue='elevated in cohort', s=21, ax=ax)
ax.set_ylim((0, 4.0))
ax.set_xlim((0, 5.5))

offsets = [
    [0.05, 0.05, 0.05, 0.05, 0.05],
    [0, 0, 0.04, -0.15, -0.1],
]
count = 0
for i, row in dfm.sort_values(by='qual').head(5).iterrows():
    label = re.sub('_', ' ', f'{row["p2"]} near \n{row["p1"]}')
    label = re.sub(r'\+', ' ', label)
    y = row['-log10(p)']
    ax.text(row['multiplier'] + offsets[0][count], y + offsets[1][count], label, fontsize=8)
    count += 1

for i, row in dfm[(dfm['qual'] > -8.0) & (dfm['multiplier'] > 3.5)].sort_values(by='qual').head(5).iterrows():
    label = re.sub('_', ' ', f'{row["p2"]} near \n{row["p1"]}')
    label = re.sub(r'\+', ' ', label)
    y = row['-log10(p)']
    ax.text(row['multiplier'] + 0.05, y, label, fontsize=8)

fig.suptitle('Phenotype-to-phenotype proximity (number cells within 50um)\nt-test for age cohort difference')
fig.savefig('bm_prox.svg')
plt.show()

dfm = df[df['metric'] == 'ratio']
dfm['-log10(p)'] = dfm['p'].apply(log10) * -1
def map_names(c: str) -> str:
    m = {
        '1': '>60 y.o.',
        '2': '20-60 y.o.',
        '3': '<20 y.o.',
    }
    return m[c]
dfm['elevated in cohort'] = dfm['higher_cohort'].apply(map_names)

fig, ax = plt.subplots(1, 1, figsize=(7, 7))
sns.scatterplot(data=dfm, x='multiplier', y='-log10(p)', hue='elevated in cohort', s=21, ax=ax)
ax.set_ylim((0, 4.0))
ax.set_xlim((0, 5.5))

offsets = [
    [0.05, 0.05, 0.05, 0.05, 0.05],
    [0, 0, 0, 0, 0],
]
count = 0
for i, row in dfm.sort_values(by='qual').head(4).iterrows():
    label = re.sub('_', ' ', f'{row["p1"]}/\n{row["p2"]}')
    label = re.sub(r'\+', ' ', label)
    y = row['-log10(p)']
    ax.text(row['multiplier'] + offsets[0][count], y + offsets[1][count], label, fontsize=8)
    count += 1

for i, row in dfm[(dfm['qual'] > -8.0) & (dfm['multiplier'] > 3.5)].sort_values(by='qual').head(5).iterrows():
    label = re.sub('_', ' ', f'{row["p1"]}/\n{row["p2"]}')
    label = re.sub(r'\+', ' ', label)
    y = row['-log10(p)']
    ax.text(row['multiplier'] + 0.05, y, label, fontsize=8)

fig.suptitle('Fraction cells of one type to another\nt-test for age cohort difference')
fig.savefig('bm_ratios.svg')
plt.show()
