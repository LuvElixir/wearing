"""Account-bound automatic briefing settings, behind existing auth and CSRF."""
from fastapi import Request
from .briefing_automation import AutomationSave, BriefingAutomation
from .task_visibility import request_owner


def install_briefing_automation_routes(app, store, briefings, schedules, *, local_devices=True):
    book=BriefingAutomation(store,briefings,schedules)
    app.state.briefing_automation=book

    @app.get('/api/briefing-automation')
    def status(request:Request):
        return book.get(request.state.identity_id,request_owner(request,local_devices=local_devices))

    @app.post('/api/briefing-automation')
    def save(request:Request,body:AutomationSave):
        return book.save(request.state.identity_id,request_owner(request,local_devices=local_devices),body)

    return book
