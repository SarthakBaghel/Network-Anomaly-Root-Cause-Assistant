from app.contracts import ErrorEnvelope


ERROR_RESPONSES = {code: {"model": ErrorEnvelope} for code in (400, 404, 409, 413, 422, 500, 503)}
