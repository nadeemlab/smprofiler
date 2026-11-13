"""Atlas-reference model training pipeline.

Orchestrates the end-to-end run:
- Extract only necessary features from reference cell atlas
- Load channel annotations
- Establish correspondence between SMProfiler channels onto atlas genes (via the manually-maintained mapping)
- Determine available per-study identity/functional channels
- Train and export one regression model per (study, functional_marker) and reference dataset
"""
import time
from pathlib import Path
from os.path import exists

from numpy.random import default_rng

from smprofiler.standalone_utilities.log_formats import colorized_logger
from smprofiler.atlas.reporting import format_elapsed, section
from smprofiler.db.accessors.atlas_models import store_models_in_db
from smprofiler.atlas.extract_relevant_atlas import ExtractRelevantCellAtlas
from smprofiler.atlas.extract_relevant_atlas import DEFAULT_ATLAS_SMALL
from smprofiler.db.exchange_data_formats.atlas_models import CellAtlasSource
from smprofiler.atlas.types import TrainingScenarioStudy
from smprofiler.atlas.types import TrainingOptions
from smprofiler.atlas.training_planning import TrainingPlanner
from smprofiler.atlas.training import TrainingStudy


logger = colorized_logger(__name__)

ATLAS_VERSION = CellAtlasSource.ALLEN_IMMUNE_HEALTH.value
_SUMMARY_WIDTH = 70

class TrainingOrchestrator:
    atlas_source: CellAtlasSource
    study: str | None
    dry_run: bool
    save_to_database: bool
    options: TrainingOptions
    plan: tuple[TrainingScenarioStudy, ...]
    planner: TrainingPlanner

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
        self.planner = TrainingPlanner(self.options)

    def run(self) -> None:
        self._extraction()
        self._planning()
        if not self.dry_run:
            self._execution()

    def _extraction(self) -> None:
        self._consider_extract_from_atlas()

    def _consider_extract_from_atlas(self) -> None:
        e = ExtractRelevantCellAtlas(database_config_file=self.database_config_file, extraction_path=DEFAULT_ATLAS_SMALL)
        if not exists(DEFAULT_ATLAS_SMALL):
            e.extract(write_table=True)
        else:
            logger.info('File already exists, not extracting again: %s', DEFAULT_ATLAS_SMALL)
        e.review_atlas_file()

    def _planning(self) -> None:
        self.planner.form_plan(self.database_config_file, self.study, self.atlas_source)
        self.plan = self.planner.plan

    def _execution(self) -> None:
        self.planner.report_plan_options(self.plan)

        random_number_generator = default_rng(42)
        run_start = time.monotonic()
        model_counter = 0
        number_validated = 0
        number_validated_std = 0
        summary_rows: list[dict] = []
        model_records: list[dict] = []
        total_models = sum(len(p.get_channels('functional')) for p in self.plan)
        for study_index, scenario in enumerate(self.plan, 1):
            t = TrainingStudy(self.options, random_number_generator)
            number_new_models, validated, validated_std = t.train_models(
                scenario,
                total_models,
                len(self.plan),
                summary_rows,
                model_records,
                study_index,
                model_counter,
            )
            model_counter += number_new_models
            number_validated += validated
            number_validated_std += validated_std

        self._store_models_in_db(self.options.database_config_file, model_records)
        self._report_execution_summary(run_start, model_counter, number_validated, number_validated_std, summary_rows)

    def _store_models_in_db(self, model_records: list[dict] | None) -> None:
        if (not self.save_to_database) or model_records is None or len(model_records) == 0:
            logger.info('Not storing models in database.')
            return
        store_models_in_db(self.database_config_file, model_records)

    def _report_execution_summary(self, run_start, number_models: int, number_validated: int, number_validated_std: int, summary_rows: list[dict]):
        total_elapsed = format_elapsed(time.monotonic() - run_start)
        section(f'Training complete — {number_models} models in {total_elapsed}')
        print(f'Number of ONNX models validated against sklearn original, prediction: {number_validated}')
        print(f'Number of ONNX models validated against sklearn original, standard deviation prediction: {number_validated_std}')
        if summary_rows:
            header = (f'  {"Study":<24}  {"Target":<16}  {"Model":<24}  {"Std method":<22}'
                      f'  {"cv_R²":>8}  {"test_R²":>8}  {"test_MAE":>10}  {"KB":>6}')
            print(header, flush=True)
            print('  ' + '─' * (_SUMMARY_WIDTH - 2), flush=True)
            for row in summary_rows:
                print(
                    f'  {row["study"]:<24}  {row["target"]:<16}  {row["model"]:<24}'
                    f'  {row["std_method"]:<22}'
                    f'  {row["cv_R²"]:>8.4f}  {row["test_R²"]:>8.4f}'
                    f'  {row["test_MAE"]:>10.4f}  {row["onnx_kb"]:>6}',
                    flush=True,
                )
        print(f'\nModels saved to: {self.options.output_directory.resolve()}', flush=True)



