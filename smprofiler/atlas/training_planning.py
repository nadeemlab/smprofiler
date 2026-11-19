from pathlib import Path

from smprofiler.atlas.types import TrainingScenarioStudy
from smprofiler.atlas.types import TrainingPlan
from smprofiler.atlas.types import TrainingOptions
from smprofiler.atlas.types import CellAtlasSource
from smprofiler.atlas.types import InherenceAtlasAnnotatedChannel
from smprofiler.atlas.channel_names_organizer import ChannelNamesOrganizer
from smprofiler.atlas.reporting import report_plan


class TrainingPlanner:
    options: TrainingOptions
    database_config_file: Path
    atlas_source: CellAtlasSource
    plan: tuple[TrainingScenarioStudy, ...]

    def __init__(self, options: TrainingOptions, database_config_file: Path, atlas_source: CellAtlasSource):
        self.options = options
        self.database_config_file = database_config_file
        self.atlas_source = atlas_source

    def form_plan(self, study: str | None) -> TrainingPlan:
        annotated_channels_per_study = self._get_annotated_channels_per_study(study)
        self.plan = tuple(filter(
            self._non_trivial,
            map(
                self._form_scenario,
                annotated_channels_per_study.items(),
            ),
        ))
        report_plan(self.plan)
        return self.plan

    def _get_annotated_channels_per_study(self, study: str) -> dict[str, tuple[InherenceAtlasAnnotatedChannel, ...]]:
        with ChannelNamesOrganizer(self.database_config_file, self.atlas_source) as o:
            if study is not None:
                annotated_channels_per_study = {study: o.get_inherence_and_atlas_annotated_study_channels(study)}
            else:
                annotated_channels_per_study = o.get_inherence_and_atlas_annotated_study_channels_all()
        return annotated_channels_per_study

    @staticmethod
    def _form_scenario(args) -> TrainingScenarioStudy:
        return TrainingScenarioStudy(*args)

    @staticmethod
    def _non_trivial(ts: TrainingScenarioStudy) -> bool:
        has_identity = len(ts.get_channels('identity')) > 0
        has_functional = len(ts.get_channels('functional')) > 0
        return has_identity and has_functional

