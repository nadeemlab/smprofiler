"""An object for storage of summarized-location data for all cells of each study."""
import pickle
from typing import cast
from json import loads

from smprofiler.workflow.common.sparse_matrix_puller import SparseMatrixPuller
from smprofiler.db.ondemand_studies_index import get_counts
from smprofiler.db.ondemand_studies_index import retrieve_expressions_index
from smprofiler.db.database_connection import DBCursor
from smprofiler.db.database_connection import retrieve_study_names
from smprofiler.db.database_connection import retrieve_primary_study
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)

SpecimenStructureCentroids = dict[int, tuple[float, float]]
StudyStructureCentroids = dict[str, SpecimenStructureCentroids]


class StructureCentroids:
    """An object for storage of summarized-location data for all cells of each study."""
    _studies: dict[str, StudyStructureCentroids]
    database_config_file: str
    writing_data_locally_only: bool

    def __init__(self, database_config_file: str | None, local_only: bool = False):
        self._studies = {}
        self.database_config_file = cast(str, database_config_file)
        self.writing_data_locally_only = local_only

    def get_studies(self) -> dict[str, StudyStructureCentroids]:
        """Retrieve the dictionary of studies.
        
        Returns
        -------
        A dictionary, indexed by study name. For each study, the value is a dictionary providing for
        each specimen name (for specimens collected as part of the given study) the list of pairs of
        pixel coordinate values representing the centroid of the shape specification for a given
        cell. The order is ascending lexicographical order of the corresponding "histological
        structure" identifier strings.
        """
        return self._studies

    def add_study_data(
        self,
        measurement_study: str,
        structure_centroids_by_specimen: StudyStructureCentroids,
    ) -> None:
        """
        Add the study with these structure centroids indexed by specimen to the collection.
        """
        self._studies[measurement_study] = structure_centroids_by_specimen

    def wrap_up_specimen(self) -> None:
        if self.writing_data_locally_only:
            return
        if len(self._studies) != 1:
            message = 'Need to write exactly 1 specimen at a time, but more or fewer than 1 study are present in buffer: %s'
            raise ValueError(message % list(self._studies.keys()))
        measurement_study_name, data = list(self._studies.items())[0]
        specimens = sorted(list(data.keys()))
        if len(specimens) != 1:
            message = 'Need to write exactly 1 specimen at a time, but more or fewer than 1 are present: %s'
            raise ValueError(message % specimens)
        specimen = specimens[0]
        study_name = retrieve_primary_study(self.database_config_file, measurement_study_name)
        with DBCursor(database_config_file=self.database_config_file, study=study_name) as cursor:
            insert_query = '''
                INSERT INTO
                ondemand_studies_index (
                    specimen,
                    blob_type,
                    blob_contents)
                VALUES (%s, %s, %s) ;
                '''
            cursor.execute(insert_query, (specimen, 'centroids', pickle.dumps(data)))
        message = 'Deleting specimen data "%s" from internal memory, since it is saved to database.'
        logger.debug(message, specimen)
        del self._studies[measurement_study_name]
        assert len(self._studies) == 0

    def load_from_db(self, study: str | None = None) -> None:
        """
        Reads the structure centroids from the database.
        """
        if study is None:
            studies = tuple(retrieve_study_names(self.database_config_file))
        else:
            studies = (study,)
        for _study in studies:
            with DBCursor(database_config_file=self.database_config_file, study=_study) as cursor:
                cursor.execute('''
                    SELECT specimen, blob_contents FROM ondemand_studies_index osi
                    WHERE osi.blob_type='centroids';
                ''')
                self._studies[_study] = {}
                while True:
                    row = cursor.fetchone()
                    if row is None:
                        break
                    obj = pickle.loads(row[1])
                    for key, value in obj.items():
                        if not key in self._studies:
                            self._studies[_study][key] = {}
                        self._studies[_study][key].update(value)

    def centroids_exist(self, study: str | None = None) -> bool:
        counts = get_counts(self.database_config_file, 'centroids', study=study)
        if any(count == 0 for count in counts.values()):
            return False
        expected = {_study: self._retrieve_expected_counts(_study) for _study in counts.keys()}
        return all(count == expected[_study] for _study, count in counts.items())

    def _retrieve_expected_counts(self, study: str) -> int | None:
        decoded_blob = retrieve_expressions_index(self.database_config_file, study)
        if decoded_blob is None:
            return None
        root = loads(decoded_blob)
        entries = root[list(root.keys())[0]]
        if len(entries) > 1:
            raise ValueError(f'Too many studies in one index file: {len(entries)}.')
        entry = entries[0]
        measurement_study = entry['specimen measurement study name']
        specimens = SparseMatrixPuller.get_pertinent_specimens(
            self.database_config_file,
            study,
            measurement_study,
            None,
        )
        return len(specimens)
