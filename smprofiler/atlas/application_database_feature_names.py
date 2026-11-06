from json import loads as json_loads

from smprofiler.atlas.channel_annotations import load_channel_annotations_from_api
from smprofiler.standalone_utilities import retrieve_from_library


class ApplicationDatabaseFeatureNames:
    """
    Provides access to SMProfiler database channel metadata.
    """
    annotations_api_url: str

    def __init__(self, annotations_api_url: str):
        self.annotations_api_url = annotations_api_url

    def get_smprofiler_channels_and_aliases(self) -> tuple[list[str], list[str], dict[str, str]]:
        """
        Returns:
            * The list of identity channels (from the SMProfiler database datasets)
            * The list of functional channels
            * The mapping of special-case aliases from SMProfiler specific study
              channel names to normalized pan-database versions.
        """
        identity_set, functional, _ = load_channel_annotations_from_api(self.annotations_api_url)
        aliases = json_loads(retrieve_from_library('channel_proxies.json', 'atlas'))
        return sorted(list(identity_set)), functional, aliases


