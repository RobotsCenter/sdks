import asyncio
import os

from robotscenter import AsyncClient


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


asyncio.run(main())
