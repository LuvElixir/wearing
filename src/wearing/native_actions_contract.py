"""Small allowlisted contract shared by the iPhone inbox and Agent connector."""
from datetime import datetime
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NAMES = {"native_devices", "native_request", "native_receipt"}
EDITS = {"calendar.update", "calendar.delete", "reminders.update", "reminders.delete"}
METHODS = {"calendar.read", "reminders.read", "location.read", "calendar.create", "reminders.create"} | EDITS
WRITES = {"calendar.create", "reminders.create"} | EDITS
Key = Annotated[str, Field(min_length=1, max_length=240)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class NativeList(Strict):
    id: Key
    title: str = Field(min_length=1, max_length=200)
    writable: bool


class NativePolicy(Strict):
    calendars: list[NativeList] = Field(default_factory=list, max_length=30)
    reminders: list[NativeList] = Field(default_factory=list, max_length=30)
    location: bool = False
    calendar_create: bool = False
    reminder_create: bool = False
    calendar_edit: bool = False
    reminder_edit: bool = False

    @model_validator(mode="after")
    def unique(self):
        for rows in (self.calendars, self.reminders):
            if len({row.id for row in rows}) != len(rows):
                raise ValueError("duplicate native list")
        return self

    def methods(self):
        result = set()
        if self.calendars:
            result.add("calendar.read")
            if self.calendar_create and any(c.writable for c in self.calendars):
                result.add("calendar.create")
            if self.calendar_edit and any(c.writable for c in self.calendars):
                result.update({"calendar.update", "calendar.delete"})
        if self.reminders:
            result.add("reminders.read")
            if self.reminder_create and any(c.writable for c in self.reminders):
                result.add("reminders.create")
            if self.reminder_edit and any(c.writable for c in self.reminders):
                result.update({"reminders.update", "reminders.delete"})
        if self.location:
            result.add("location.read")
        return result


class CalendarRead(Strict):
    calendar_ids: list[Key] = Field(min_length=1, max_length=30)
    start: str
    end: str
    limit: int = Field(default=100, ge=1, le=100)

    @model_validator(mode="after")
    def range(self):
        if not 0 < (date(self.end) - date(self.start)).total_seconds() <= 31 * 86400:
            raise ValueError("calendar range exceeds 31 days")
        return self


class RemindersRead(Strict):
    calendar_ids: list[Key] = Field(min_length=1, max_length=30)
    completed: bool = False
    limit: int = Field(default=100, ge=1, le=100)


class CreateReminder(Strict):
    calendar_id: Key
    title: str = Field(min_length=1, max_length=300)
    notes: str = Field(default="", max_length=5000)
    due: str | None = None
    # SDK 57's legacy reminder readback omits allDay. Do not perform an
    # all-day write whose intended date semantics cannot be verified afterward.
    all_day: Literal[False] = False

    @field_validator("all_day", mode="before")
    @classmethod
    def supported_all_day(cls, value):
        if value is not False:
            raise ValueError("all-day reminders cannot yet be verified")
        return value

    @model_validator(mode="after")
    def valid(self):
        if not self.title.strip():
            raise ValueError("title required")
        if self.due is not None:
            date(self.due)
        return self


class CreateCalendar(Strict):
    calendar_id: Key
    title: str = Field(min_length=1, max_length=300)
    notes: str = Field(default="", max_length=5000)
    start: str
    end: str
    all_day: bool = False

    @model_validator(mode="after")
    def valid(self):
        if not self.title.strip() or not 0 < (date(self.end) - date(self.start)).total_seconds() <= 31 * 86400:
            raise ValueError("invalid event")
        return self


def date(value):
    if not isinstance(value, str) or len(value) > 60:
        raise ValueError("invalid date")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("date must include timezone")
    return result


class Snapshot(Strict):
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    recurring: bool
    occurrence_start: str | None
    mutable: bool


class NativeReference(Strict):
    record_ref: str = Field(pattern=r"^native_[a-f0-9]{32}:[0-9]{1,2}$")


class NativeUpdate(NativeReference):
    patch: dict

    @model_validator(mode="after")
    def valid_patch(self):
        if not self.patch or not set(self.patch) <= {"title", "notes", "start", "end", "completed"}:
            raise ValueError("unsupported native patch")
        for key, value in self.patch.items():
            if key == 'completed':
                if type(value) is not bool: raise ValueError('invalid completion')
            elif not isinstance(value, str) or len(value) > (1000 if key == 'notes' else 300):
                raise ValueError('invalid native text')
            elif key == 'title' and not value.strip(): raise ValueError('missing title')
            elif key in {'start', 'end'}: date(value)
        return self


def parameters(method, value, policy):
    models = {"calendar.read": CalendarRead, "reminders.read": RemindersRead,
              "location.read": Strict, "calendar.create": CreateCalendar, "reminders.create": CreateReminder,
              **{name: NativeUpdate if name.endswith('.update') else NativeReference for name in EDITS}}
    if method not in models or method not in policy.methods():
        raise ValueError("capability not allowed")
    params = models[method].model_validate(value).model_dump()
    if method in EDITS:
        allowed = {'title', 'notes', 'start', 'end'} if method.startswith('calendar.') else {'title', 'notes', 'completed'}
        if not set(params.get('patch', {})) <= allowed:
            raise ValueError('unsupported patch for native entity')
        return params  # The trusted read receipt supplies the list and native ID.
    if method != "location.read":
        lists = policy.calendars if method.startswith("calendar.") else policy.reminders
        ids = params.get("calendar_ids", [params.get("calendar_id")])
        allowed = {c.id for c in lists if method not in WRITES or c.writable}
        if len(set(ids)) != len(ids) or not set(ids) <= allowed:
            raise ValueError("list not selected")
    return params


class NativeOutcome(Strict):
    status: Literal["succeeded", "cancelled", "failed", "unknown"]
    code: Literal["ok", "denied", "permission", "inactive", "expired", "native_error", "readback", "interrupted", "conflict", "unsupported"]
    data: dict = Field(default_factory=dict)
