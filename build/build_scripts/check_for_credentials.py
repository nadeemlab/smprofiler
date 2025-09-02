"""A simple utility to check availability of credentials for development tasks."""
import configparser
import json
from os import environ
from os.path import exists
from os.path import join
import sys
import subprocess


class CredentialChecker:
    """PyPI and Docker credentials checker."""

    def __init__(self):
        self.checkers = {
            'pypi': self.check_for_pypi_credentials,
            'docker': self.check_for_docker_credentials,
        }
        self.result = None

    def explain_arguments(self):
        accounts = self.get_accounts()
        print(f'Need to supply one of: {accounts}')
        sys.exit(1)

    def get_accounts(self):
        return self.checkers.keys()

    def get_result(self):
        return self.result

    def report_result(self):
        result = self.get_result()
        print(result, end='')
        if result == 'not_found':
            sys.exit(1)
        else:
            sys.exit()

    def check_for_credentials(self, account):
        checker = self.checkers[account]
        if checker():
            self.result = 'found'
        else:
            self.result = 'not_found'

    def check_for_pypi_credentials(self):
        config = configparser.ConfigParser()
        pypirc = join(environ['HOME'], '.pypirc')
        if not exists(pypirc):
            return False
        config.read(pypirc)
        if 'smprofiler' not in config.sections():
            return False
        fields = ['repository', 'username', 'password']
        if not all([x in config['smprofiler'] for x in fields]):
            return False
        return True

    def check_for_docker_credentials(self):
        configfile = join(environ['HOME'], '.docker', 'config.json')
        print(configfile)
        if not exists(configfile):
            return False
        config = json.loads(open(configfile, 'rt', encoding='utf-8').read())
        if 'credsStore' in config:
            store = config["credsStore"]
            if store in ['desktop', 'osxkeychain']:
                result = subprocess.run(
                    [f'docker-credential-{store}', 'list'], encoding='utf-8',
                    capture_output=True, check=True)
                if len(json.loads(result.stdout)) == 0:
                    return False
        if (not 'auths' in config) and (not 'credsStore' in config):
            return False
        if len(config['auths'].keys()) == 0:
            return False
        return True


def main():
    checker = CredentialChecker()
    if len(sys.argv) < 2:
        checker.explain_arguments()
    account = sys.argv[1]
    if account not in checker.get_accounts():
        checker.explain_arguments()
    checker.check_for_credentials(account)
    checker.report_result()


if __name__ == '__main__':
    main()
