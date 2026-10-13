from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.models.enums import AgentName, ImplementationStatus


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
        use_enum_values=True,
    )


class AgentActivity(ApiModel):
    event_id: str
    request_id: str
    agent: AgentName
    perception: str
    decision: str
    action: str
    result: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class UseCaseEntry(ApiModel):
    use_case_id: str
    name: str
    module: str
    owner: str
    implementation_status: ImplementationStatus

