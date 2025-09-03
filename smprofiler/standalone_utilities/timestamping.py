
from datetime import datetime
from datetime import timezone

from pytz import timezone as pytz_timezone  # type: ignore

GUESSED_LOCAL_TIMEZONE = None
try:
    GUESSED_LOCAL_TIMEZONE = pytz_timezone(str(datetime.now().astimezone().tzinfo))
except Exception:
    pass

def now() -> datetime:
    return datetime.now(tz=GUESSED_LOCAL_TIMEZONE)
