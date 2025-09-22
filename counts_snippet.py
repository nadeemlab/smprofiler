from os.path import expanduser

from smprofiler.ondemand.computers.counts_computer import CountsComputer
from smprofiler.ondemand.job_reference import ComputationJobReference
from smprofiler.ondemand.cell_data_cache import CellDataCache
from smprofiler.db.database_connection import DBConnection

def count_precomputed_dichotomized():
    study = open('study.txt', 'rt', encoding='utf-8').read().rstrip() 
    job = ComputationJobReference(17, study, 'WCM1')
    connection = DBConnection(database_config_file=expanduser('~/.smprofiler_db.config.aws.prod'), study=study)
    connection.__enter__()
    computer = CountsComputer(job, CellDataCache(), connection)
    computer.compute()


if __name__=='__main__':
    count_precomputed_dichotomized()


