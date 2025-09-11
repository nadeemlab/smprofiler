
from os import get_terminal_size
import re
from collections import deque
from time import time as get_time_seconds

from smprofiler.standalone_utilities.chainable_destructable_resource import ChainableDestructableResource

class TerminalScrollingBufferInterface(ChainableDestructableResource):
    def __init__(self, **kwargs):
        pass

    def add_line(self, line: str, sticky_header: str | None = None) -> None:
        pass

    def reset_header(self) -> None:
        pass


class TerminalScrollingBuffer(TerminalScrollingBufferInterface, ChainableDestructableResource):
    """
    Show a scrolling status window in the terminal with displayed lines incrementally
    added/cycled out over time.

    A "sticky" header can be shown optionally to indicate some context for a given
    section of logs.

    `number_lines` controls the height of the window.

    Excessively long lines are truncated and indicated with an arrow character.

    If `show_section_count=True`, the sticky header will include the count of the
    number of "sections" that have been displayed so far, including the current one.

    This is meant to run in interactive mode, at the end to dumping all log lines
    (with no formatting) to the terminal. This can be helpful for detailed
    inspection of logs only after a whole process has completed, with incremental
    inspection when in progress.

    Note that the resource-release pattern is used, so this buffer can be used
    in a standalone way as a context manager, or as an attribute of another
    object that registers the buffer as a dependent resources.

    Usage:

    ```
    from time import sleep
    with TerminalScrollingBuffer(number_lines=7) as b:
        for i in range(1, 31, 1):
            sleep(0.1)
            sticky_header = f'Group {int(i/10)}' if i%10 == 0 else None
            b.add_line(f'Line item #{i}', sticky_header=sticky_header)
    ```
    """
    number_lines: int
    lines: deque[str]
    sticky_header: str
    all_lines: list[str]
    section_count: int
    show_section_count: bool
    start_time: float

    def __init__(self, number_lines: int = 4, show_section_count: bool=True):
        self.number_lines = number_lines
        self.lines = deque(maxlen=number_lines)
        self.sticky_header = ''
        self.section_count = 0
        self.all_lines = []
        self.show_section_count = show_section_count
        self._start()

    def release(self) -> None:
        self._dump_all()

    def add_line(self, line: str, sticky_header: str | None = None) -> None:
        if sticky_header is not None:
            self.sticky_header = sticky_header
            self.section_count += 1
        lines = line.split('\n')
        if len(lines) > 1:
            for _line in lines:
                self.add_line(_line)
        else:
            self.all_lines.append(line)
            _line = self._sanitize(line)
            self.lines.append(_line)
            self._update_display()

    def _dump_all(self) -> None:
        for line in self.all_lines:
            print(line)

    def reset_header(self) -> None:
        self.sticky_header = ''

    def _start(self) -> None:
        self.start_time = get_time_seconds()
        self._update_display(initial=True)

    def _update_display(self, initial: bool=False) -> None:
        if not initial:
            self._clear_previous_window()
        shown_count = 0
        self._show_header()
        for line in self.lines:
            print(self._format_status_line(line))
            shown_count +=1
        for _ in range(self.number_lines - shown_count):
            print('')
        elapsed = int(get_time_seconds() - self.start_time)
        self._show_horizontal_divider_text(f'{elapsed}s')

    def _clear_previous_window(self) -> None:
        print('\33[2K\r', end='')
        print('\033[A\33[2K\r' * (self.number_lines + 2), end='')

    def _show_header(self) -> None:
        header = ''
        if self.show_section_count:
            if self.sticky_header != '':
                header = self.sticky_header + f' ({self.section_count})'
            else:
                header= self.sticky_header
        self._show_horizontal_divider_text(header)

    def _show_horizontal_divider_text(self, text: str) -> None:
        if text != '':
            text = ' ' + text + ' '
        size = get_terminal_size().columns
        padding = '' if len(text) > size - 2 else '\u2501' * (size - 2 - len(text))
        print('\u2501'*2 + '\033[95m' + text + '\033[0m' + padding)

    @staticmethod
    def _sanitize(line: str) -> str:
        _line = re.sub('\n', '\u2591', line)
        return _line

    @staticmethod
    def _format_status_line(line: str) -> str:
        size = get_terminal_size().columns
        if len(line) > size:
            line = line[0:size-1] + '\u2192'
        return '\033[34m' + line + '\033[0m'
