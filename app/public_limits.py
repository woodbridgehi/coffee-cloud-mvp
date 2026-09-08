"""Bounded per-process public traffic and streaming connection admission."""
import time
from collections import Counter

from starlette.responses import JSONResponse


class PublicLimits:
    def __init__(self, app, read_limit=240, write_limit=30, stream_limit=1000):
        self.app = app
        self.read_limit = read_limit
        self.write_limit = write_limit
        self.stream_limit = stream_limit
        self.windows = {}
        self.streams = Counter()
        self.total_streams = 0
        self.last_cleanup = 0

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        public_path = path.startswith('/api/v1/public/')
        payment_create = path.startswith('/api/v1/orders/') and path.endswith('/payments')
        payment_read = path.startswith('/api/v1/payments/') and scope.get('method') in {'GET', 'HEAD'}
        if scope['type'] != 'http' or not (public_path or payment_create or payment_read):
            return await self.app(scope, receive, send)
        now = time.monotonic()
        if now - self.last_cleanup >= 60:
            self.windows = {k: v for k, v in self.windows.items() if now - v[0] < 60}
            self.last_cleanup = now
        # ASGI client comes from the server's explicitly trusted proxy handling.
        # Never trust arbitrary X-Forwarded-For here.
        ip = (scope.get('client') or ('unknown', 0))[0]
        write = scope.get('method') not in {'GET', 'HEAD', 'OPTIONS'}
        parts = path.split('/')
        resource = '/'.join(parts[:7])
        keys = [(('ip', ip, write), self.write_limit if write else self.read_limit)]
        if write:
            keys.append((('resource', resource), self.write_limit * 2))
        admitted = True
        for key, limit in keys:
            start, count = self.windows.get(key, (now, 0))
            if now - start >= 60:
                start, count = now, 0
            if key not in self.windows and len(self.windows) >= 20000:
                admitted = False
                break
            self.windows[key] = (start, count + 1)
            if count >= limit:
                admitted = False
        stream = path.endswith('/events') and scope.get('method') == 'GET'
        stream_keys = [('ip', ip), ('order', resource)]
        if stream and (self.total_streams >= self.stream_limit or
                       self.streams[stream_keys[0]] >= 12 or self.streams[stream_keys[1]] >= 3):
            admitted = False
        if not admitted:
            return await JSONResponse({'detail': '请求过于频繁或连接数已达上限，请稍后重试'},
                                      status_code=429, headers={'Retry-After': '60'})(scope, receive, send)
        if stream:
            self.total_streams += 1
            self.streams.update(stream_keys)
        try:
            await self.app(scope, receive, send)
        finally:
            if stream:
                self.total_streams -= 1
                for key in stream_keys:
                    self.streams[key] -= 1
                    if self.streams[key] == 0:
                        del self.streams[key]
