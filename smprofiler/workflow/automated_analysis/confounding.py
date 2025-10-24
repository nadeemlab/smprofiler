"""Determine if a result might be confounded by another result (i.e. not necessarily valid)."""

from typing import Literal

from smprofiler.workflow.automated_analysis.types import Result

class SimpleConfounding:
    """
    Estimate whether ratios result (result2) may be confounded by singleton result
    (result1). This can happen when:
      - either the numerator or denominator phenotype in result2 is the singleton
        phenotype of result1
      - either of the two phenotypes for proximity in result2 is the singleton
        phenotype of result1,
    and the direction of association implied by both results is the same.
    """
    r1: Result
    r2: Result

    def __init__(self, result1: Result, result2: Result):
        self.r1 = result1
        self.r2 = result2

    def probable_confounding(self) -> bool:
        return self._check_result_types() and (
            (not self._incomparable_due_to_cohort_set()) and
            (self._get_common_phenotype() is not None) and
            self._direction_of_association_consistent()
        )

    def _check_result_types(self) -> bool:
        c1 = self.r1.case
        c2 = self.r2.case
        return (
            c1.metric == 'fractions' and
            c2.metric == 'fractions' and
            c1.other is None and
            c2.other is not None
        ) or (
            c1.metric == 'fractions' and
            c2.metric == 'proximity' and
            c1.other is None
        )

    def _incomparable_due_to_cohort_set(self) -> bool:
        c1 = self.r1.case
        c2 = self.r2.case
        return len(set(c1.cohorts).intersection(set(c2.cohorts))) == 0

    def _get_common_phenotype(self) -> Literal['phenotype', 'other', None]:
        c1 = self.r1.case
        c2 = self.r2.case
        if c1.phenotype == c2.phenotype:
            return 'phenotype'
        if c1.phenotype == c2.other:
            return 'other'
        return None

    def _direction_of_association_consistent(self) -> bool:
        common = self._get_common_phenotype()
        if self.r2.case.metric == 'fractions':
            if common == 'phenotype':
                return (self.r1.higher_cohort == self.r2.higher_cohort) or (self.r1.lower_cohort() == self.r2.lower_cohort())
            if common == 'other':
                return (self.r1.higher_cohort == self.r2.lower_cohort()) or (self.r1.lower_cohort() == self.r2.higher_cohort)
        if self.r2.case.metric == 'proximity':
            return self.r1.higher_cohort == self.r2.higher_cohort
        return False


