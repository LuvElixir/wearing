"""First-run context routes behind the host authentication/CSRF/identity gates."""
from fastapi import HTTPException, Request

from .onboarding import OnboardingError, SaveOnboarding
from .task_visibility import request_owner


def install_onboarding_routes(app, book, *, local_devices=True):
    def call(fn, request, *args):
        try:
            return fn(request.state.identity_id, *args,
                      owner_scope=request_owner(request, local_devices=local_devices))
        except OnboardingError as error:
            raise HTTPException(error.status, str(error)) from None

    @app.get('/api/onboarding')
    def get(request: Request):
        return call(book.get, request)

    @app.post('/api/onboarding')
    def save(request: Request, body: SaveOnboarding):
        return call(book.save, request, body)
