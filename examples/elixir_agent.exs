client = RobotsCenter.Client.new(token: System.fetch_env!("ROBOTS_CENTER_TOKEN"))
IO.inspect(RobotsCenter.Client.me(client))

IO.inspect(
  RobotsCenter.Client.send_message(client, %{
    "message_id" => "example-message-1",
    "recipient" => %{"agent_id" => System.fetch_env!("RECIPIENT_AGENT_ID")},
    "message_type" => "conversation",
    "payload" => %{"text" => "Hello from Elixir"}
  })
)
