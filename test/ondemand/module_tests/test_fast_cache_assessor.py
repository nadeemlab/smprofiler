
from smprofiler.ondemand.cache_assessment import CacheAssessment

def test_assessor():
    assessor = CacheAssessment(database_config_file=None, study='Melanoma intralesional IL2')
    assessor.assess_and_act()

    assessor = CacheAssessment(database_config_file=None, study='Breast cancer IMC')
    assessor.assess_and_act()

if __name__=='__main__':
    test_assessor()
