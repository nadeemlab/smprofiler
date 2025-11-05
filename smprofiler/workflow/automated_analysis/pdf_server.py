import datetime

from pymupdf import open as pymupdf_open
from pymupdf import Point as pymupdf_Point
from pymupdf import Document as pymupdf_Document

from smprofiler.db.database_connection import DBCursor

def form_current_date() -> str:
    today = datetime.date.today()
    return today.strftime('%b %-d %Y')


class PDFReportServer:
    database_config_file: str
    study: str

    def __init__(self, database_config_file:str, study: str):
        self.database_config_file = database_config_file
        self.study = study

    def datestamp_and_retrieve(self) -> bytes:
        data = self._retrieve_pdf_from_database()
        data = open('analysis_summary.pdf', 'rb').read()
        doc = pymupdf_Document(stream=data)
        doc = pymupdf_open('analysis_summary.pdf')
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
            raise ValueError(f'No saved PDFs for study: {self.study}')
        return rows[0][0]


