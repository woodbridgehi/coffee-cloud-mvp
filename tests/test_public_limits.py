import asyncio
from app.public_limits import PublicLimits


def test_rate_limit_and_untrusted_forwarded_header():
    async def run():
        statuses = []
        async def app(scope, receive, send):
            await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        limiter = PublicLimits(app, read_limit=2)
        async def send(message):
            if message['type'] == 'http.response.start': statuses.append(message['status'])
        for n in range(3):
            await limiter({'type': 'http', 'path': '/api/v1/public/devices/x/menu', 'method': 'GET',
                           'client': ('same-ip', 1), 'headers': [(b'x-forwarded-for', str(n).encode())]}, None, send)
        assert statuses == [200, 200, 429]
    asyncio.run(run())


def test_sse_limit_releases_after_cancellation():
    async def run():
        hold = asyncio.Event()
        async def app(scope, receive, send): await hold.wait()
        limiter = PublicLimits(app)
        scope = {'type': 'http', 'path': '/api/v1/public/orders/id/events', 'method': 'GET', 'client': ('ip', 1)}
        statuses = []
        async def send(message):
            if message['type'] == 'http.response.start': statuses.append(message['status'])
        tasks = [asyncio.create_task(limiter(scope, None, send)) for _ in range(3)]
        await asyncio.sleep(0)
        await limiter(scope, None, send)
        assert statuses == [429]
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        assert limiter.total_streams == 0 and not limiter.streams
    asyncio.run(run())
