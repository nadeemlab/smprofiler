
from attrs import define
from attrs import field
from numpy import matrix
from numpy import array
from numpy.linalg import inv
from numpy import matmul

from smprofiler.workflow.automated_analysis.types import ResultSignificance

@define
class Limits:
    """
    Limits for significance involving p value and effect size, enforced with the
    `acceptable` method.
    A highest p-value is enforced, in such a way that it is only allowed to be
    achieved at a given (extreme) effect size.
    Similarly a lowest effect size is enforced, in such a way that it is only
    allowed to be achieved at a given (extreme) p-value.

    Linear interpolation between these two data points of extrema creates the
    threshold of tradeoff between borderline insignificant cases.

    Separately, hard limits (max p-value and min effect size) are also enforced.
    """
    effect_min: float
    p_required_at_effect_min: float
    p_max: float
    effect_required_at_p_max: float
    coefficients: tuple[float, float] = field(init=False)

    def __attrs_post_init__(self):
        self.coefficients = tuple(array(matmul(
            inv(matrix([
                [self.p_max, self.effect_required_at_p_max],
                [self.p_required_at_effect_min, self.effect_min],
            ])),
            matrix([1, 1]).transpose(),
        ).transpose()).tolist()[0])

    def acceptable(self, result: ResultSignificance) -> bool:
        effect = result.effect
        p = result.p
        c = self.coefficients
        linear_term = c[0] * p + c[1] * effect - 1
        return (effect > self.effect_min) and (p < self.p_max) and (linear_term > 0)

DEFAULT_LIMITS = Limits(1.3, 0.01, 0.2, 2.0)
LIMITS_SEVERE = Limits(1.5, 0.005, 0.2, 3.0) 

@define
class FullUsageAssessor:
    """
    This filter imposes limits on result sets intended to account for the phenonmenon of
    too many null values omitted from the sample set before statistic evaluation.
    Usually the statistical test will be good enough at detecting this, since
    p-values get worse as less data is used, but a more conservative (severe)
    limit is often needed, usually indicated by suspiciously high effect size.

    Starting at effect sizes at the provided threshold, limits on the defect in
    the fraction of data used are imposed incrementally for each unit increase
    in the effect size. 
    
    The above is achieved by linear interpolation between the initial effect size
    at which the limits begin to be imposed, and the final effect size after which
    100% source data usage is required.
    """
    effect_size_initial_threshold: float
    effect_size_final_threshold: float

    def acceptable(self, r: ResultSignificance) -> bool:
        effect = r.effect
        if effect <= self.effect_size_initial_threshold:
            return True
        if effect >= self.effect_size_final_threshold:
            return r.fraction_data_used == 1.0
        effect_diff = effect - self.effect_size_initial_threshold
        limit = self._marginal_fraction_data_used_per_unit_effect_size() * effect_diff
        return r.fraction_data_used_defect() <= limit

    def _marginal_fraction_data_used_per_unit_effect_size(self) -> float:
        return 1.0 / (self.effect_size_final_threshold - self.effect_size_initial_threshold)

DEFAULT_USAGE_LIMITS = FullUsageAssessor(2.0, 3.0)

