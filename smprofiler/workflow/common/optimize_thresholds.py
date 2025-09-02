
from typing import Callable

from attrs import define
from numpy import array as np_array
from numpy import ndarray
from numpy import isscalar
from scipy.optimize import minimize_scalar
from scipy.optimize import basinhopping
from scipy.optimize import OptimizeResult
from scipy.spatial.distance import jaccard
from pandas import concat
from pandas import DataFrame
from pandas import Series

from smprofiler.standalone_utilities.terminal_scrolling import TerminalScrollingBuffer
from smprofiler.standalone_utilities.terminal_scrolling import TerminalScrollingBufferInterface

@define
class ColumnNamings:
    channel: Callable[[str], str]
    phenotype: Callable[[str], str]

Signature = tuple[tuple[str, ...], tuple[str, ...]]

class SignatureConcordance:
    """
    This class is for evaluating the objective function for our threshold optimizer. It
    is based on the Jaccard index.
    """
    df: DataFrame
    signatures: dict[str, Signature]
    channels: tuple[str, ...]
    column_namings: ColumnNamings
    ignore_negatives: bool

    def __init__(self,
        df: DataFrame,
        signatures: dict[str, Signature],
        channels: tuple[str, ...],
        column_namings: ColumnNamings,
        ignore_negatives: bool=False,
    ):
        self.df = df
        self.signatures = signatures
        self.channels = channels
        self.column_namings = column_namings
        self.ignore_negatives = ignore_negatives

    def evaluate(self, channel_thresholds: ndarray) -> float:
        if isscalar(channel_thresholds):
            channel_thresholds = [channel_thresholds]
        return self._evaluate(dict(zip(self.channels, channel_thresholds)))

    def _evaluate(self, thresholds: dict[str, float]) -> float:
        objective = 0
        for phenotype, signature in self.signatures.items():
            objective += self._evaluate_phenotype(phenotype, signature, thresholds)
        return objective / len(self.signatures)

    def _evaluate_phenotype(self, phenotype: str, signature: Signature, thresholds: dict[str, float]) -> float:
        positives = signature[0]
        negatives = signature[1]
        def _meets(threshold: float, value: float) -> bool:
            return value > threshold
        def _membership(row) -> int:
            for p in set(positives).intersection(thresholds.keys()):
                if not _meets(thresholds[p], row[self.column_namings.channel(p)]):
                    return int(0)
            if not self.ignore_negatives:
                for n in set(negatives).intersection(thresholds.keys()):
                    if _meets(thresholds[n], row[self.column_namings.channel(n)]):
                        return int(0)
            return int(1)
        ostensible_members = self.df.apply(_membership, axis=1)
        phenotype_assignments = self.df[self.column_namings.phenotype(phenotype)]
        return self._compare(phenotype_assignments, ostensible_members)

    def _compare(self, mask1: Series, mask2: Series) -> float:
        vector1 = mask1.to_numpy()
        vector2 = mask2.to_numpy()
        return float(jaccard(vector1 ,vector2))


class ThresholdOptimizer:
    """
    Optimize channel thresholds to achieve concordance between actual cell phenotype assignments
    and expected assignments in terms of signatures defined as given channel combinations.

    This works in two phases:
    1. Individual channel optimization. If a signature/phenotype has only one positive marker, that
       phenotype's assignments are compared with the positive/negative assignments for this channel,
       with respect to the Jaccard index. The actual optimization procedure is `scipy.minimize_scalar`.
    2. All-channels all-signatures optimization. The multivariate optimizer `scipy.basinhopping`
       is used to optimize the average Jaccard index over the phenotypes with given signatures, by
       adjusting thresholds/gates for all channels.

    `cell_data` should be a DataFrame with a 'sample' column, a number of numeric columns for each
    measured channel, and a number of binary 0/1 columns for phenotype assignments.

    Each sample's cell data is considered as a separate optimization problem.

    The names of the channel columns should be expressible using a function `channel_column_namer`
    which accepts a channel name and produces the corresponding column name.

    Similarly the names of the phenotype assignment columns should be expressible using a function
    `phenotype_column_namer` which accepts a phenotype name and produces the corresponding column name.

    The channels to be optimized should be explicitly indicated in `channels`.

    The signature definitions should be provided in `signatures` by phenotype name, with value
    a pair consisting of the tuple of positive markers/channels and the tuple of negative markers/channels.

    If `verbose` is set, logs are printed to the console. If in addition `interactive` is set, a
    scrolling buffer is used to display a fixed number of statements during optimization, then
    upon completion the whole logs are dumped to the console.
    """
    cell_data: DataFrame
    channels: tuple[str, ...]
    signatures: dict[str, tuple[tuple[str, ...], tuple[str, ...]]]
    column_namings: ColumnNamings
    single_channel_phase_subsample: int
    main_phase_subsample: int
    main_phase_iterations: int
    main_phase_step: int
    terminal_scroller: TerminalScrollingBufferInterface
    thresholds: DataFrame

    def __init__(self,
        cell_data: DataFrame,
        channels: tuple[str, ...],
        signatures: dict[str, tuple[tuple[str, ...], tuple[str, ...]]],
        channel_column_namer: Callable[[str], str],
        phenotype_column_namer: Callable[[str], str],
        single_channel_phase_subsample: int=1000,
        main_phase_subsample: int=1000,
        main_phase_iterations: int=20,
        main_phase_step: int=3,
        verbose: bool=True,
        interactive: bool=True,
    ):
        self.cell_data = cell_data
        self.channels = channels
        self.signatures = signatures
        self.column_namings = ColumnNamings(channel_column_namer, phenotype_column_namer)
        self.single_channel_phase_subsample = single_channel_phase_subsample
        self.main_phase_subsample = main_phase_subsample
        self.main_phase_iterations = main_phase_iterations
        self.main_phase_step = main_phase_step
        if verbose:
            self.terminal_scroller = TerminalScrollingBuffer(number_lines=15, interactive=interactive)
        else:
            self.terminal_scroller = TerminalScrollingBufferInterface()
        self._determine_optimal_thresholds()

    def get_optimal_thresholds(self) -> DataFrame:
        return self.thresholds

    def _determine_optimal_thresholds(self):
        thresholds = None
        self.terminal_scroller.add_line(self.cell_data.columns)
        for sample, sample_df in self.cell_data.groupby('sample', observed=True):
            self.terminal_scroller.add_line(f'Sample {sample}', sticky_header=f'Sample {sample}')
            t = self._determine_optimal_thresholds_one_sample(sample, sample_df)
            if thresholds is None:
                thresholds = t
            else:
                thresholds = concat([thresholds, t], axis=0)
            self.terminal_scroller.reset_header()
        self.thresholds = thresholds
        self.terminal_scroller.finish()

    def _determine_optimal_thresholds_one_sample(self, sample: str, sample_df: DataFrame) -> DataFrame:
        singly_optimized = self._single_channel_optimization(sample_df)
        optimal_thresholds = self._main_phase_optimization(sample_df, singly_optimized)
        t = DataFrame(tuple(zip(
            [sample] * len(self.channels),
            self.channels,
            list(optimal_thresholds.x),
            np_array([singly_optimized[c] for c in self.channels]),
            [float(sample_df[self.column_namings.channel(c)].mean()) for c in self.channels],
        )), columns=['sample', 'channel', 'final_threshold', 'singly_optimized', 'original_mean'])
        self._report_sample_thresholds(sample_df, t, optimal_thresholds, sample)
        return t

    def _single_channel_optimization(self, sample_df: DataFrame) -> dict[str, float | None]:
        self.terminal_scroller.add_line('Determining initial thresholds for individual channels in isolation.')
        singly_optimized = dict(zip(self.channels, [None for _ in self.channels]))
        for phenotype, signature in self.signatures.items():
            if len(signature[0]) == 1:
                channel = signature[0][0]
                e = SignatureConcordance(
                    sample_df.sample(self.single_channel_phase_subsample),
                    {phenotype: signature},
                    [channel],
                    self.column_namings,
                    ignore_negatives=True,
                )
                initial_value = float(sample_df[self.column_namings.channel(channel)].mean())
                optimal_thresholds: OptimizeResult = minimize_scalar(e.evaluate, initial_value, bounds=(0, 2*initial_value))
                singly_optimized[channel] = float(optimal_thresholds.x)
                self.terminal_scroller.add_line(f'{channel}: {optimal_thresholds.x} ')
        return singly_optimized

    def _main_phase_optimization(self, sample_df: DataFrame, singly_optimized) -> OptimizeResult:
        self.terminal_scroller.add_line('\n')
        self.terminal_scroller.add_line('Adjusting thresholds for better concordance considering *all* signatures.')
        e = SignatureConcordance(sample_df.sample(self.main_phase_subsample), self.signatures, self.channels, self.column_namings)
        v0 = np_array([singly_optimized[c] for c in self.channels])
        def print_fun(x, f, accepted):
            self.terminal_scroller.add_line(f'Objective value {f} at {x} accepted by optimizer: {accepted}')
        return basinhopping(
            e.evaluate,
            v0,
            niter=self.main_phase_iterations,
            stepsize=self.main_phase_step,
            minimizer_kwargs={'bounds': [(0, 100)]*len(self.channels)},
            callback=print_fun,
        )

    def _report_sample_thresholds(self, sample_df: DataFrame, thresholds: DataFrame, optimal_thresholds: OptimizeResult, sample: str):
        self.terminal_scroller.add_line('')
        self.terminal_scroller.add_line(f'Best thresholds ({sample}):')
        self.terminal_scroller.add_line(thresholds)
        self.terminal_scroller.add_line(f'Average Jaccard index over signatures in {self.main_phase_subsample} subsample: {optimal_thresholds.fun}')
        self.terminal_scroller.add_line('Evaluating Jaccard over all...')
        v = SignatureConcordance(sample_df, self.signatures, self.channels, self.column_namings).evaluate(optimal_thresholds.x)
        self.terminal_scroller.add_line(f'Average Jaccard index over signatures in all {sample_df.shape[0]}: {v}')
