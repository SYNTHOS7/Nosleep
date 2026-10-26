"""Bound request bodies before multipart parsing or document publication."""
from starlette.responses import JSONResponse


class BodyTooLarge(Exception):
    pass


class UploadLimitMiddleware:
    def __init__(self, app, max_bytes=50 * 1024 * 1024):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] not in {'POST','PUT','PATCH'}:
            return await self.app(scope, receive, send)
        length = dict(scope.get('headers', [])).get(b'content-length')
        try:
            declared = int(length) if length else 0
        except ValueError:
            return await JSONResponse({'message':'Invalid Content-Length'}, status_code=400)(scope, receive, send)
        if declared > self.max_bytes:
            return await JSONResponse({'message':'Upload exceeds the 50 MiB request limit'}, status_code=413)(scope, receive, send)
        count = 0
        started = False
        async def bounded_receive():
            nonlocal count
            message = await receive()
            count += len(message.get('body', b''))
            if count > self.max_bytes:
                raise BodyTooLarge()
            return message
        async def tracked_send(message):
            nonlocal started
            if message['type'] == 'http.response.start':
                started = True
            await send(message)
        try:
            await self.app(scope, bounded_receive, tracked_send)
        except BodyTooLarge:
            if started:
                raise
            await JSONResponse({'message':'Upload exceeds the request limit'}, status_code=413)(scope, receive, send)
