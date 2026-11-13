from pathlib import Path

from smprofiler.atlas.types import TrainingOptions
from smprofiler.atlas.types import TrainingScenarioStudy
from smprofiler.atlas.channel_names_organizer import ChannelNamesOrganizer
from smprofiler.db.exchange_data_formats.atlas_models import CellAtlasSource
from smprofiler.standalone_utilities.log_formats import colorized_logger
from smprofiler.atlas.reporting import section
from smprofiler.atlas.reporting import subsection

logger = colorized_logger(__name__)


class TrainingPlanner:
    options: TrainingOptions
    plan: tuple[TrainingScenarioStudy, ...]

    def __init__(self, options: TrainingOptions):
        self.options = options

    def form_plan(self, database_config_file: Path, study: str | None, atlas_source: CellAtlasSource) -> tuple[TrainingScenarioStudy, ...]:
        with ChannelNamesOrganizer(database_config_file, atlas_source) as o:
            if study is not None:
                annotated_channels = {study: o.get_inherence_and_atlas_annotated_study_channels(study)}
            else:
                annotated_channels = o.get_inherence_and_atlas_annotated_study_channels_all()

        def _form_scenario(args) -> TrainingScenarioStudy:
            return TrainingScenarioStudy(*args)

        def _non_trivial(ts: TrainingScenarioStudy) -> bool:
            has_identity = len(ts.get_channels('identity')) > 0
            has_functional = len(ts.get_channels('functional')) > 0
            return has_identity and has_functional

        self.plan = tuple(filter(_non_trivial, map(_form_scenario, annotated_channels.items())))
        self._report_plan()
        return self.plan

    def report_plan_options(self, plan: tuple[TrainingScenarioStudy, ...]) -> None:
        total_models = sum(len(p.get_channels('functional')) for p in plan)
        section(
            f'Atlas-reference model training -- '
            f'{len(plan)} studies, {total_models} models total'
        )
        logger.info('Output directory: %s', self.options.output_directory.resolve())
        if self.options.max_cells:
            logger.info('Max atlas cells per study: %s', f'{self.options.max_cells:,}')
        else:
            logger.info('Using full atlas (no cell limit)')
        logger.info('Cross-validation folds: %d', self.options.cv_folds)

    def _report_plan(self) -> None:
        section('DRY RUN -- Training plan')
        total_models = sum(len(p.get_channels('functional')) for p in self.plan)
        for p in self.plan:
            subsection(f'Study: {p.study_handle}')
            identity = p.get_channels('identity')
            logger.info(
                '  Identity features (%d): %s', len(identity), identity
            )
            functional = p.get_channels('functional')
            for fc in functional:
                logger.info(' => model: target="%s"  features=%s', fc.study_specific_name, list(map(lambda c: c.study_specific_name, identity)))
        print(f'\nTotal: {len(self.plan)} studies, {total_models} models to train.', flush=True)


