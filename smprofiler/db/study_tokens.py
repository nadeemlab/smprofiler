"""Deal with naming related to study collection/aggregation tags."""
import re
import json

from smprofiler.db.exchange_data_formats.study import StudyHandle

class StudyCollectionNaming:
    """Deal with naming related to study collection/aggregation tags."""
    @classmethod
    def strip_extract_token(cls, study_handle: StudyHandle) -> tuple[str, str | None]:
        return cls.strip_token(study_handle.handle)

    @classmethod
    def strip_token(cls, study: str) -> tuple[str, str | None]:
        pattern = fr'{cls.infix()}({cls.tag_pattern()})$'
        match = re.search(pattern, study)
        if match:
            _extract = match.groups()[0]
            _study = re.sub(pattern, '', study)
        else:
            _study = study
            _extract = None
        return _study, _extract

    @classmethod
    def name_study(cls, study: str, extract: str) -> str:
        if not re.search(fr'{cls.tag_pattern()}$', extract):
            raise ValueError(f'"{extract}" is not a valid study collection identifier.')
        return cls.infix().join((study, extract))

    @classmethod
    def is_untagged(cls, study_handle: StudyHandle) -> bool:
        _, extract = cls.strip_extract_token(study_handle)
        return extract is None

    @classmethod
    def is_untagged_name(cls, study_name: str) -> bool:
        _, extract = cls.strip_extract_token(StudyHandle(handle=study_name, display_name_detail=''))
        return extract is None

    @classmethod
    def tagged_with(cls, study_handle: StudyHandle, tag: str) -> bool:
        _, extract = cls.strip_extract_token(study_handle)
        return extract == tag

    @staticmethod
    def infix() -> str:
        return ' collection: '

    @staticmethod
    def tag_pattern() -> str:
        return r'[a-z0-9\-]{1,513}'

    @classmethod
    def matches_tag_pattern(cls, tag: str) -> bool:
        return re.search(fr'^{cls.tag_pattern()}$', tag) is not None

    @classmethod
    def extract_study_from_file(cls, study_json: str) -> str:
        with open(study_json, 'rt', encoding='utf-8') as file:
            study = json.loads(file.read())
            study_name = study['Study name']
            if 'Study collection' in study:
                collection = study['Study collection']
                study_name = cls.name_study(study_name, collection)
        return study_name
