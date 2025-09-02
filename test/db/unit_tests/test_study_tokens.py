"""Test study tokens."""

from smprofiler.db.study_tokens import StudyCollectionNaming
from smprofiler.db.exchange_data_formats.study import StudyHandle

def test_study_tokens():
    initial = 'Study name ABCD collection: abc-def'
    study, extract = StudyCollectionNaming.strip_token(initial)
    assert study == 'Study name ABCD'
    assert extract == 'abc-def'
    recreated = StudyCollectionNaming.name_study(study, extract)
    assert initial == recreated

    handle = StudyHandle(handle=initial, display_name_detail='')
    assert not StudyCollectionNaming.is_untagged(handle)
    assert StudyCollectionNaming.tagged_with(handle, extract)
    handle = StudyHandle(handle='Study name ABCD', display_name_detail='')
    assert StudyCollectionNaming.is_untagged(handle)

    study_file = 'study.small.json'
    tagged = 'Melanoma intralesional IL2 collection: abc-123'
    assert StudyCollectionNaming.extract_study_from_file(study_file) == tagged


if __name__=='__main__':
    test_study_tokens()
