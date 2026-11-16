from pathlib import Path

from smprofiler.atlas.types import TrainingScenarioStudy
from smprofiler.atlas.types import TrainingPlan
from smprofiler.atlas.types import TrainingOptions
from smprofiler.atlas.types import CellAtlasSource
from smprofiler.atlas.channel_names_organizer import ChannelNamesOrganizer
from smprofiler.atlas.reporting import report_plan


class TrainingPlanner:
    options: TrainingOptions
    plan: tuple[TrainingScenarioStudy, ...]

    def __init__(self, options: TrainingOptions):
        self.options = options

    def form_plan(self, database_config_file: Path, study: str | None, atlas_source: CellAtlasSource) -> TrainingPlan:
        with ChannelNamesOrganizer(database_config_file, atlas_source) as o:
            if study is not None:
                annotated_channels_per_study = {study: o.get_inherence_and_atlas_annotated_study_channels(study)}
            else:
                annotated_channels_per_study = o.get_inherence_and_atlas_annotated_study_channels_all()

        def _form_scenario(args) -> TrainingScenarioStudy:
            return TrainingScenarioStudy(*args)

        def _non_trivial(ts: TrainingScenarioStudy) -> bool:
            has_identity = len(ts.get_channels('identity')) > 0
            has_functional = len(ts.get_channels('functional')) > 0
            return has_identity and has_functional

        self.plan = tuple(filter(_non_trivial, map(_form_scenario, annotated_channels_per_study.items())))
        report_plan(self.plan)
        return self.plan

