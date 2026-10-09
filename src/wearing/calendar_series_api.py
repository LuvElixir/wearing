"""Identity-bound recurrence commands shared with the product MCP."""
from typing import Literal
from fastapi import HTTPException, Request
from pydantic import Field, ValidationError, model_validator
from .calendar_series import CalendarSeriesBook, SeriesDraft, SeriesError, Strict, Template


class SeriesCommand(Strict):
    action: Literal['list','get','query','create','update','archive','restore','override','cancel','reset']
    series_id: str | None = Field(default=None, pattern=r'^series_[a-f0-9]{32}$')
    revision: int | None = Field(default=None, ge=1)
    request_key: str | None = Field(default=None, min_length=1, max_length=120)
    draft: SeriesDraft | None = None
    template: Template | None = None
    occurrence_key: str | None = None
    start: str | None = None
    end: str | None = None
    timezone: str | None = None
    after: str | None = Field(default=None, pattern=r'^series_[a-f0-9]{32}$')
    include_deleted: bool | None = None

    @model_validator(mode='after')
    def fields_for_action(self):
        allowed = {'list':{'after','include_deleted'},'get':{'series_id','occurrence_key'},'query':{'start','end','series_id','timezone'},'create':{'request_key','draft'},
                   'update':{'series_id','revision','request_key','draft'},'archive':{'series_id','revision','request_key'},'restore':{'series_id','revision','request_key'},
                   'override':{'series_id','revision','request_key','occurrence_key','template'},'cancel':{'series_id','revision','request_key','occurrence_key'},'reset':{'series_id','revision','request_key','occurrence_key'}}[self.action]
        required = allowed - ({'after','include_deleted'} if self.action=='list' else {'series_id'} if self.action=='query' else {'occurrence_key'} if self.action=='get' else set())
        supplied = self.model_fields_set-{'action'}
        if supplied-allowed or any(getattr(self,f) is None for f in required): raise ValueError('该日历动作的字段不完整或包含多余参数')
        return self


def execute(book: CalendarSeriesBook, identity, command):
    value = SeriesCommand.model_validate(command)
    args = value.model_dump(exclude_unset=True); action = args.pop('action')
    if action == 'list': return book.list(identity,**args)
    if action == 'get': return book.get(identity,**args)
    if action == 'query': return book.query(identity,**args)
    return book.mutate(identity,action=action,**args)


def install_calendar_series_routes(app, book):
    @app.post('/api/calendar-series')
    def command(request: Request, body: SeriesCommand):
        try: return execute(book,request.state.identity_id,body.model_dump(exclude_unset=True))
        except SeriesError as error: raise HTTPException(error.status,str(error)) from error
        except (ValueError,KeyError,ValidationError) as error: raise HTTPException(422,'请检查日期、时区与重复规则，原系列未改变。') from error
