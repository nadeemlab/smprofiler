"""Logs basic indicator of amount of progress, at a configurable interval."""

from smprofiler.standalone_utilities.log_formats import colorized_logger

_logger = colorized_logger(__name__)

class FractionalProgressReporter:
    """Logs basic indicator of amount of progress, at a configurable interval."""
    def __init__(self, size, parts=2, task_and_done_message=('task', None), logger=_logger):
        task_description, done_message = task_and_done_message
        self.size = size
        self.parts = parts
        self.task_description = task_description
        self.done_message = done_message
        self.logger = logger
        self.counter = 0
        self.key_times = [round((i+1) * (size / parts)) for i in range(parts)]

    def increment(self, iteration_details=None):
        self.counter = self.counter + 1
        if self.counter in self.key_times:
            percent = round(100 * (self.counter / self.size))
            self.report(percent, iteration_details=iteration_details)

    def report(self, percent, iteration_details=None):
        arguments = [percent, self.task_description]
        message = '%s%% finished with %s.'
        if iteration_details is not None:
            arguments.append(iteration_details)
            message = '%s%% finished with %s. (%s ...)'
        self.logger.info(message, *arguments)

    def done(self):
        appendix = f'({self.size} iterations)'
        if self.done_message is not None:
            self.logger.info('%s %s',  self.done_message, appendix)
        else:
            self.logger.info('Done %s. %s', self.task_description, appendix)
