"""A convenience reporter of time performance. Keeps track of time used by specific named processes
and reports an aggregation as a text table.
"""

import time
from typing import Literal
from typing import get_args

import pandas as pd
import numpy as np

ReportOrganization = Literal['average time spent', 'total time spent', 'frequency', 'fraction']


class PerformanceTimer:
    """An object of this class makes it easy to track which part of complex
    branching code is taking a long time, with only a few additional lines of
    monitoring code.

    Use record_timepoint at key moments, supplying a short message/title that
    indicates what the context, typically an indication of what has just completed.
    Whenever you want to assess the time performance, use report_string
    to get a markdown representation of a table of times, on the basis of *pairs*
    of code locations (as indicated by your messages) occurring consecutively.
    Included in the report are fraction of time spent, total time spent (seconds),
    average time spent per occurrence, frequency of occurrence.
    """

    def __init__(self):
        self.times = {}
        self.previous_time = None
        self.previous_message = None
        self.message_order = {}

    def record_timepoint(self, message):
        now = time.perf_counter()
        if self.previous_time is not None:
            diff = now - self.previous_time
            transition = (message, self.previous_message)
            if transition not in self.times:
                self.times[transition] = []
            self.times[(message, self.previous_message)].append(diff)
        self.previous_time = now
        self.previous_message = message
        if not message in self.message_order:
            number = len(self.message_order)
            self.message_order[message] = number

    def report(self, organize_by: ReportOrganization) -> pd.DataFrame:
        transitions = sorted(
            list(self.times.keys()),
            key=lambda x: (self.message_order[x[0]], self.message_order[x[1]]),
        )
        records = []
        all_totals = sum(np.sum(self.times[t]) for t in transitions)
        for transition in transitions:
            total = np.sum(self.times[transition])
            frequency = len(self.times[transition])
            records.append({
                'from': transition[1],
                'to': transition[0],
                'average time spent': total / frequency,
                'total time spent': total,
                'frequency': frequency,
                'fraction': total / all_totals,
            })
        df = pd.DataFrame(records)
        if organize_by in get_args(ReportOrganization):
            df.sort_values(by=organize_by, inplace=True, ascending=False)
        return df

    def report_string(self, organize_by: ReportOrganization):
        df = self.report(organize_by=organize_by)
        return df.to_markdown(index=False)


class PerformanceTimerReporter:
    """Logger/reporter of performance timer results."""
    timer: PerformanceTimer

    def __init__(self, performance_report_file: str, logger):
        self.performance_report_file = performance_report_file
        self.logger = logger
        self.timer = PerformanceTimer()

    def record_timepoint(self, moment_name: str):
        self.timer.record_timepoint(moment_name)

    def wrap_up_timer(self):
        """Concludes low-level performance metric collection."""
        df = self.timer.report(organize_by='fraction')
        self.logger.info('Report to: %s', self.performance_report_file)
        df.to_csv(self.performance_report_file, index=False)
