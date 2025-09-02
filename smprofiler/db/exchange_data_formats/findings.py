from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class FindingCreate(BaseModel):
    study: str
    email: str
    url: str
    description: str
    background: str
    p_value: float
    effect_size: float
    id_token: str

class FindingStatus(str, Enum):
    pending_review = 'pending_review'
    published = 'published'
    deferred_decision = 'deferred_decision'
    rejected = 'rejected'

class Finding(BaseModel):
    """A single user-contributed finding."""
    id: int
    study: str
    submission_datetime: datetime
    publication_datetime: datetime | None
    status: FindingStatus
    orcid_id: str
    name: str
    family_name: str
    email: str
    url: str
    description: str
    background: str
    p_value: float
    effect_size: float

finding_fields = [
    'study',
    'submission_datetime',
    'publication_datetime',
    'status',
    'orcid_id',
    'name',
    'family_name',
    'email',
    'url',
    'description',
    'background',
    'p_value',
    'effect_size',
]
