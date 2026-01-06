
from smprofiler.workflow.automated_analysis.auto_assessor import StudyAutoAssessor
from smprofiler.workflow.automated_analysis.auto_assessor import PhenotypeCriteria

def test_case_enumeration():
    P = PhenotypeCriteria
    
    phenotypes = StudyAutoAssessor._enumerate_phenotypes_from(('A', 'B', 'C', 'D'), (1,))
    expected = (
        P(positive_markers=('A',), negative_markers=()),
        P(positive_markers=('B',), negative_markers=()),
        P(positive_markers=('C',), negative_markers=()),
        P(positive_markers=('D',), negative_markers=()),
    )
    if not phenotypes == expected:
        print('phenotypes:')
        print('\n'.join(str(p) for p in phenotypes))
        raise ValueError

    phenotypes = StudyAutoAssessor._enumerate_phenotypes_from(('A', 'B', 'distance to X', 'D'), (1,))
    expected = (
        P(positive_markers=('A',), negative_markers=()),
        P(positive_markers=('B',), negative_markers=()),
        P(positive_markers=(), negative_markers=('distance to X',)),
        P(positive_markers=('D',), negative_markers=()),
    )
    if not phenotypes == expected:
        print('phenotypes:')
        print('\n'.join(str(p) for p in phenotypes))
        raise ValueError

    phenotypes = StudyAutoAssessor._enumerate_phenotypes_from(('A', 'B', 'C', 'D'), (2,))
    expected = (
        P(positive_markers=('A',), negative_markers=('B',)),
        P(positive_markers=('B',), negative_markers=('A',)),
        P(positive_markers=('A', 'B'), negative_markers=()),
        P(positive_markers=('A',), negative_markers=('C',)),
        P(positive_markers=('C',), negative_markers=('A',)),
        P(positive_markers=('A', 'C'), negative_markers=()),
        P(positive_markers=('A',), negative_markers=('D',)),
        P(positive_markers=('D',), negative_markers=('A',)),
        P(positive_markers=('A', 'D'), negative_markers=()),
        P(positive_markers=('B',), negative_markers=('C',)),
        P(positive_markers=('C',), negative_markers=('B',)),
        P(positive_markers=('B', 'C'), negative_markers=()),
        P(positive_markers=('B',), negative_markers=('D',)),
        P(positive_markers=('D',), negative_markers=('B',)),
        P(positive_markers=('B', 'D'), negative_markers=()),
        P(positive_markers=('C',), negative_markers=('D',)),
        P(positive_markers=('D',), negative_markers=('C',)),
        P(positive_markers=('C', 'D'), negative_markers=()),
    )
    if not phenotypes == expected:
        print('phenotypes:')
        print('\n'.join(str(p) for p in phenotypes))
        raise ValueError


if __name__=='__main__':
    test_case_enumeration()

