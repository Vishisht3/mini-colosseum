"""Quit must stop the active run (no more model calls) and shut the backend down."""
import asyncio

from backend import server


def test_shutdown_stops_orchestrator_and_cancels_task():
    stopped = []

    class FakeOrchestrator:
        def stop(self):
            stopped.append(True)

    async def main():
        async def sleep_forever():
            await asyncio.sleep(3600)

        task = asyncio.create_task(sleep_forever())
        server.active_orchestrator = FakeOrchestrator()
        server.active_task = task
        try:
            result = await server.shutdown()
            await asyncio.sleep(0.05)
            return result, task
        finally:
            server.active_orchestrator = None
            server.active_task = None

    result, task = asyncio.run(main())
    assert result == {"status": "shutting_down"}
    assert stopped == [True]
    assert task.cancelled() or task.cancelling()
