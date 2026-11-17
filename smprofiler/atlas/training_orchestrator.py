"""
Atlas-reference model training pipeline.

Orchestrates the end-to-end run:
- Extract only necessary features from reference cell atlas
- Load channel/marker annotations
- Establish correspondence between SMProfiler channels onto atlas genes (via the manually-maintained mapping)
- Determine available per-study identity/functional channels
- Train and export one regression model per (study, functional_marker) pair and reference dataset
"""
import time
from pathlib import Path
from os.path import exists

from numpy.random import default_rng

from smprofiler.db.accessors.atlas_models import StoredAtlasModels
from smprofiler.atlas.reporting import report_execution_summary
from smprofiler.atlas.extract_relevant_atlas import ExtractRelevantCellAtlas
from smprofiler.atlas.extract_relevant_atlas import DEFAULT_ATLAS_SMALL
from smprofiler.atlas.types import CellAtlasSource
from smprofiler.atlas.types import TrainingScenarioStudy
from smprofiler.atlas.types import TrainingOptions
from smprofiler.atlas.types import TrainingProgress
from smprofiler.atlas.training_planning import TrainingPlanner
from smprofiler.atlas.training_study import TrainingStudy
from smprofiler.atlas.reporting import report_plan_options
from smprofiler.standalone_utilities.log_formats import colorized_logger


logger = colorized_logger(__name__)


class TrainingOrchestrator:
    atlas_source: CellAtlasSource
    study: str | None
    dry_run: bool
    save_to_database: bool
    options: TrainingOptions
    plan: tuple[TrainingScenarioStudy, ...]
    planner: TrainingPlanner
    progress: TrainingProgress

    def __init__(
        self,
        database_config_file: Path,
        atlas_source: str,
        output_directory: Path,
        max_cells: int | None = None,
        study: str | None = None,
        cv_folds: int = 5,
        dry_run: bool = False,
        save_to_database: bool = False,
    ):
        self.database_config_file = database_config_file
        self.atlas_source = CellAtlasSource(atlas_source)
        self.output_directory = output_directory
        self.max_cells = max_cells
        self.study = study
        self.cv_folds = cv_folds
        self.dry_run = dry_run
        self.save_to_database = save_to_database
        self.options = TrainingOptions(
            self.output_directory,
            self.max_cells,
            self.cv_folds,
            self.database_config_file,
            Path(DEFAULT_ATLAS_SMALL),
        )

    def run(self) -> None:
        self._extraction()
        self._planning()
        if not self.dry_run:
            self._execution()

    def _extraction(self) -> None:
        self._consider_extract_from_atlas()

    def _consider_extract_from_atlas(self) -> None:
        e = ExtractRelevantCellAtlas(database_config_file=self.database_config_file, extraction_path=Path(DEFAULT_ATLAS_SMALL))
        if not exists(DEFAULT_ATLAS_SMALL):
            e.extract(write_table=True)
        else:
            logger.info('File already exists, not extracting again: %s', DEFAULT_ATLAS_SMALL)
        e.review_atlas_file()

    def _planning(self) -> None:
        self.planner = TrainingPlanner(self.options)
        self.planner.form_plan(self.database_config_file, self.study, self.atlas_source)
        self.plan = self.planner.plan

    def _execution(self) -> None:
        report_plan_options(self.plan, self.options)
        random_number_generator = default_rng(42)
        run_start = time.monotonic()
        self.progress = TrainingProgress(0, 0, 0, [], [])
        total_models = sum(len(p.get_channels('functional')) for p in self.plan)
        for study_index, scenario in enumerate(self.plan, 1):
            t = TrainingStudy(self.options, scenario, random_number_generator, self.progress)
            t.train_models(
                total_models,
                len(self.plan),
                study_index,
            )
        self._store_models_in_db()
        report_execution_summary(run_start, self.options, self.progress)

    def _store_models_in_db(self) -> None:
        model_records = self.progress.model_records
        if (not self.save_to_database) or model_records is None or len(model_records) == 0:
            logger.info('Not storing models in database.')
            return
        StoredAtlasModels.store_models_in_db(self.options.database_config_file, model_records)


