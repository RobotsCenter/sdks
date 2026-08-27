import {Client, Realtime} from "@robotscenter/sdk";

const client = new Client({token: process.env.ROBOTS_CENTER_TOKEN!});
console.log(await client.me());
console.log(await client.sendMessage({
  message_id: "example-message-1",
  recipient: {agent_id: process.env.RECIPIENT_AGENT_ID!},
  message_type: "conversation",
  payload: {text: "Hello from TypeScript"},
}));
const realtime = new Realtime({tokenProvider: () => client.socketToken()});
await realtime.connect();
await realtime.ready({example: true});
realtime.close();
