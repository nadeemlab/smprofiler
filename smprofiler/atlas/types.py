from pathlib import Path

from attrs import define

from smprofiler.db.exchange_data_formats.atlas_models import InherenceAtlasAnnotatedChannel


@define
class TrainingScenarioStudy:
    study_handle: str
    channels: tuple[InherenceAtlasAnnotatedChannel, ...]

    def get_channels(self, group: str) -> tuple[InherenceAtlasAnnotatedChannel, ...]:
        return tuple(filter(lambda c: c.inherence == group, self.channels))

@define
class TrainingOptions:
    output_directory: Path
    max_cells: int | None
    cv_folds: int
    database_config_file: Path
    parquet_atlas_path: Path


