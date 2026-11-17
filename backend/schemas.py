from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from services.attendance import Status


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ClassInput(Input):
    name: str = Field(min_length=1, max_length=32)


class NamesInput(Input):
    names: str = Field(min_length=1, max_length=10000)
    bulk: bool = False
    preview: bool = False


class StudentInput(Input):
    name: str | None = Field(default=None, max_length=97)
    class_id: int | None = Field(default=None, gt=0)


class MarkInput(Input):
    status: Status
    version: str = Field(max_length=32)
    reason: str | None = Field(default=None, max_length=300)


class UserInput(Input):
    telegram_id: int = Field(gt=0, lt=2**52)


class BlockInput(Input):
    blocked: bool


class AccessInput(Input):
    class_id: int = Field(gt=0)
    operation: Literal['manager_add', 'manager_remove', 'recipient_add', 'recipient_remove', 'history_on', 'history_off']


class ScheduleInput(Input):
    time: str = Field(max_length=5)
    timezone: str = Field(min_length=1, max_length=64)
    weekdays: list[Annotated[int, Field(ge=0, le=6)]] = Field(min_length=1, max_length=7)
    enabled: bool
    reminder_one: str | None = Field(default=None, min_length=5, max_length=5)
    reminder_two: str | None = Field(default=None, min_length=5, max_length=5)


class SendInput(Input):
    request_id: str = Field(pattern=r'^[a-f0-9]{32}$')


class SettingsInput(Input):
    school: str = Field(min_length=1, max_length=120)
