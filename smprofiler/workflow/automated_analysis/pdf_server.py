import datetime

from psycopg.errors import UndefinedTable
from pymupdf import Point as pymupdf_Point
from pymupdf import Document as pymupdf_Document

from smprofiler.db.database_connection import DBCursor

def form_current_date() -> str:
    today = datetime.date.today()
    return today.strftime('%b %-d %Y')


class NoReportFound(ValueError):
    def __init__(self, study: str):
        super().__init__(f'No report found for study: {study}')


class PDFReportServer:
    database_config_file: str | None
    study: str

    def __init__(self, database_config_file:str | None, study: str):
        self.database_config_file = database_config_file
        self.study = study

    def exists(self) -> bool:
        try:
            with DBCursor(database_config_file=self.database_config_file, study=self.study) as cursor:
                cursor.execute('SELECT COUNT(*) FROM pdf_reports ;')
                rows = tuple(cursor.fetchall())
                count = rows[0][0]
            return count > 0
        except UndefinedTable:
            return False

    def datestamp_and_retrieve(self) -> bytes:
        data = self._retrieve_pdf_from_database()
        doc = pymupdf_Document(stream=data)
        doc[0].insert_text(
            pymupdf_Point(450, 18),
            f'Report generated {form_current_date()}',
            fontname = 'courier-oblique',
            fontsize = 9,
            rotate = 0,
        )
        return doc.tobytes()

    def _retrieve_pdf_from_database(self) -> bytes:
        with DBCursor(database_config_file=self.database_config_file, study=self.study) as cursor:
            query = '''
            SELECT pr.blob
            FROM pdf_reports as pr
            ORDER BY pr.date_generated DESC ;
            '''
            cursor.execute(query)
            rows = tuple(cursor.fetchall())
        if len(rows) == 0:
            raise NoReportFound(self.study)
        return rows[0][0]


