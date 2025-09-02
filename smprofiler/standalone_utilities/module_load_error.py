"""Convenience exception for notifying user of intended installation procedures."""
class SuggestExtrasException:
    """Convenience exception for notifying user of intended installation procedures."""

    def __init__(self, module_not_found_error, extras_section):
        self.suggest_extras(extras_section)
        raise module_not_found_error

    def suggest_extras(self, extras_section):
        print('\n'.join([
            '\u001b[33m',
            'Got a module not found error.',
            'Did you install the required extras with:\u001b[0m\u001b[32m',
            f'    pip install "smprofiler[{extras_section}]"',
            '\u001b[33m?',
            '\u001b[0m',
        ]))
