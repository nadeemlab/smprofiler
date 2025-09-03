"""Plot the distributions for each possible 8-bit floating point specification."""

from matplotlib import pyplot as plt
import matplotlib.pyplot as plt

from smprofiler.standalone_utilities.float8 import float_format
from smprofiler.standalone_utilities.float8 import generate_metadata_table


def create_comparison_plot():
    n_bins = 50
    _, axs = plt.subplots(4, 6, sharey=True, tight_layout=True)
    bases = [2, 3, 5, 10]
    for J, B in list(enumerate(bases)):
        for I in range(6):
            f = float_format(I + 1, B)
            try:
                _, df = generate_metadata_table(f)
                values = df['decoded_value']
                print(df.to_string())
            except OverflowError:
                values = []
            axs[J, I].hist(values, bins=n_bins)

    for ax, (J, B) in zip(axs[:,0], list(enumerate(bases))):
        ax.set_ylabel(f'Base {B}', rotation=0)

    for ax, I in zip(axs[3,:], range(7)):
        ax.set_xlabel(f'Exponent bits {I + 1}\nFixed bits {8 - I - 1}', rotation=0)

    plt.show()


if __name__=='__main__':
    create_comparison_plot()
