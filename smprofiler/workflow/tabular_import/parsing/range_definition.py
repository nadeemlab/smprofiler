"""Data structure representing a convenience scope or range for database records."""
from attr import define

@define
class RangeDefinition:
    """Data structure representing a convenience scope or range for database records."""
    scope_identifier: str
    tablename: str
    lowest_value: int
    highest_value: int | None

class RangeDefinitionFactory:
    """Create and finalize range definitions."""
    @classmethod
    def create(cls,
        scope_identifier: str,
        initial_index: int,
        tablename: str,
    ) -> RangeDefinition:
        lowest_value = initial_index
        return RangeDefinition(scope_identifier, tablename, lowest_value, None)

    @classmethod
    def finalize(cls, range_definition: RangeDefinition, highest_value: int):
        range_definition.highest_value = highest_value
