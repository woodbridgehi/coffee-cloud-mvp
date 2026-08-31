"""Bound unauthenticated merchant request bodies before JSON parsing/KDF work."""
from starlette.responses import JSONResponse


class MerchantBoundary:
    def __init__(self, app, max_body=65536):
        self.app, self.max_body = app, max_body

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not scope['path'].startswith(('/api/v1/merchant/', '/assets/merchant')):
            return await self.app(scope, receive, send)

        async def safe_send(message):
            if message['type'] == 'http.response.start':
                message['headers'] = [*message['headers'],
                    (b'cache-control', b'no-store'), (b'x-content-type-options', b'nosniff'),
                    (b'referrer-policy', b'no-referrer'), (b'x-frame-options', b'DENY')]
                if scope['path'].endswith('merchant.html'):
                    message['headers'].append((b'content-security-policy',
                        b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"))
            await send(message)

        body = bytearray()
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            body.extend(message.get('body', b''))
            if len(body) > self.max_body:
                response = JSONResponse({'error': {'code': 'BODY_TOO_LARGE', 'message': '请求内容过大'}}, status_code=413)
                return await response(scope, receive, safe_send)
            if not message.get('more_body', False):
                break
        sent = False

        async def replay():
            nonlocal sent
            if sent:
                return await receive()
            sent = True
            return {'type': 'http.request', 'body': bytes(body), 'more_body': False}

        await self.app(scope, replay, safe_send)
