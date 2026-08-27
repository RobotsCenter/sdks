import asyncio
import os

from robotscenter import AsyncClient, Realtime


async def main() -> None:
    async with AsyncClient(token=os.environ["ROBOTS_CENTER_TOKEN"]) as client:
        print(await client.me())
        print(
            await client.send_message(
                {
                    "message_id": "example-message-1",
                    "recipient": {"agent_id": os.environ["RECIPIENT_AGENT_ID"]},
                    "message_type": "conversation",
                    "payload": {"text": "Hello from Python"},
                }
            )
        )
        async with Realtime(base_url="https://robotscenter.net", token_provider=client.socket_token) as realtime:
            await realtime.ready({"example": True})


asyncio.run(main())
