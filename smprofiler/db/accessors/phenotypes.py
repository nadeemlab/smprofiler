"""Convenience accessors/manipulators for phenotype data."""

from smprofiler.db.simple_method_cache import simple_instance_method_cache
from smprofiler.db.exchange_data_formats.metrics import PhenotypeSymbol
from smprofiler.db.exchange_data_formats.metrics import PhenotypeCriteria
from smprofiler.db.accessors.study import StudyAccess
from smprofiler.db.database_connection import SimpleReadOnlyProvider


class PhenotypeNotFoundError(Exception):
    """Raised when information is requested for a phenotype that cannot be located by the given
    name."""


class PhenotypesAccess(SimpleReadOnlyProvider):
    """Access to phenotype-related database data."""
    def get_phenotype_symbols(self, study: str) -> tuple[PhenotypeSymbol, ...]:
        components = StudyAccess(self.cursor).get_study_components(study)
        query = '''
        SELECT DISTINCT cp.symbol, cp.identifier
        FROM cell_phenotype_criterion cpc
        JOIN cell_phenotype cp ON cpc.cell_phenotype=cp.identifier
        WHERE cpc.study=%s
        ORDER BY cp.symbol
        ;
        '''
        self.cursor.execute(query, (components.analysis,))
        rows = self.cursor.fetchall()
        return tuple(
            PhenotypeSymbol(handle_string=row[0], identifier=row[1])
            for row in rows
        )

    def get_composite_phenotype_identifiers(self) -> tuple[str, ...]:
        query = '''
        SELECT cpc.cell_phenotype FROM cell_phenotype_criterion cpc
        ;
        '''
        self.cursor.execute(query)
        return tuple(row[0] for row in self.cursor.fetchall())

    @simple_instance_method_cache(maxsize=2000)
    def get_phenotype_criteria(self, study: str, phenotype_symbol: str) -> PhenotypeCriteria:
        query = '''
        SELECT cs.symbol, cpc.polarity
        FROM cell_phenotype_criterion cpc
        JOIN cell_phenotype cp ON cpc.cell_phenotype = cp.identifier
        JOIN chemical_species cs ON cs.identifier = cpc.marker
        JOIN study_component sc ON sc.component_study=cpc.study
        WHERE cp.symbol=%s AND sc.primary_study=%s
        ;
        '''
        self.cursor.execute(query, (phenotype_symbol, study),)
        rows = self.cursor.fetchall()
        if len(rows) == 0:
            singles_query = '''
            SELECT symbol, 'positive' as polarity FROM chemical_species
            WHERE symbol=%s
            ;
            '''
            self.cursor.execute(singles_query, (phenotype_symbol,))
            rows = self.cursor.fetchall()
            if len(rows) == 0:
                raise PhenotypeNotFoundError(phenotype_symbol)
        positives = sorted([
            marker for marker, polarity in rows if polarity == 'positive'
        ])
        negatives = sorted([
            marker for marker, polarity in rows if polarity == 'negative'
        ])
        return PhenotypeCriteria(positive_markers=tuple(positives), negative_markers=tuple(negatives))

    def get_phenotype_criteria_by_identifier(
            self,
            phenotype_handle: str,
            analysis_study: str
        ) -> PhenotypeCriteria:
        self.cursor.execute('''
            SELECT cs.symbol, cpc.polarity
            FROM cell_phenotype_criterion cpc
            JOIN chemical_species cs ON cs.identifier=cpc.marker
            WHERE cpc.cell_phenotype=%s AND cpc.study=%s
            ;
            ''',
            (phenotype_handle, analysis_study,),
        )
        rows = self.cursor.fetchall()
        positives = sorted([str(row[0]) for row in rows if row[1] == 'positive'])
        negatives = sorted([str(row[0]) for row in rows if row[1] == 'negative'])
        return PhenotypeCriteria(
            positive_markers=tuple(positives), negative_markers=tuple(negatives),
        )

    @simple_instance_method_cache(maxsize=1000)
    def get_channel_names(self, study: str) -> tuple[tuple[str, ...], ...]:
        components = StudyAccess(self.cursor).get_study_components(study)
        self.cursor.execute('''
            SELECT cs.symbol, cs.name
            FROM biological_marking_system bms
            JOIN chemical_species cs ON bms.target=cs.identifier
            WHERE bms.study=%s
            ;
            ''',
            (components.measurement,),
        )
        return tuple((row[0], row[1]) for row in self.cursor.fetchall())
