import asyncio
import uuid
import pytest
from app.order_stream import order_stream
from app.order_events import ORDER_CHANGED


def test_ready_stream_stays_open_until_collection_then_unsubscribes():
    async def run():
        class Broker:
            queue = asyncio.Queue()
            closed = False
            def subscribe(self, *_): return self.queue
            def unsubscribe(self, *_): self.closed = True
        class Service:
            collected = None
            def get(self, *args, **kwargs):
                return {'status':'READY','pickupRequired':True,'collectedAt':self.collected}
            def with_live_progress(self, snapshot): return snapshot
        broker, service = Broker(), Service()
        stream = order_stream(broker, service, uuid.uuid4(), 'token')
        assert '"collectedAt":null' in await anext(stream)
        service.collected = '2026-09-08T01:00:00Z'
        broker.queue.put_nowait(ORDER_CHANGED)
        assert service.collected in await asyncio.wait_for(anext(stream),1)
        with pytest.raises(StopAsyncIteration): await anext(stream)
        assert broker.closed
    asyncio.run(run())


def test_queued_stream_refreshes_when_other_orders_change_without_own_event(monkeypatch):
    async def run():
        class Broker:
            def subscribe(self,*_): return asyncio.Queue()
            def unsubscribe(self,*_): pass
        class Service:
            calls=0
            def get(self,*args,**kwargs):
                self.calls+=1
                return {'status':'QUEUED','queue':{'aheadCount':3-self.calls}}
            def with_live_progress(self,snapshot): return snapshot
        async def timeout(awaitable,timeout):
            assert timeout==5
            awaitable.close()
            raise TimeoutError
        monkeypatch.setattr(asyncio,'wait_for',timeout)
        service=Service();stream=order_stream(Broker(),service,uuid.uuid4(),'token')
        assert '"aheadCount":2' in await anext(stream)
        assert '"aheadCount":1' in await anext(stream)
        await stream.aclose()
    asyncio.run(run())
