defmodule RobotsCenter.Realtime do
  @moduledoc "Phoenix v2 agent-channel client with fresh-token reconnect and subscription replay."
  use GenServer
  alias PhoenixClient.Message
  alias RobotsCenter.RealtimeError
  @default_timeout 10_000
  @heartbeat_interval 20_000
  @backoff [1_000, 2_000, 5_000, 10_000, 30_000]
  defstruct [
    :base_url,
    :token_provider,
    :join_payload,
    :socket,
    :channel,
    :owner,
    :heartbeat_timer,
    :reconnect_timer,
    subscriptions: %{},
    reconnect_attempt: 0,
    stopping: false
  ]

  def start_link(opts), do: GenServer.start_link(__MODULE__, {opts, self()}, name: opts[:name])
  def close(server), do: GenServer.stop(server, :normal)

  def push(server, event, payload \\ %{}, timeout \\ @default_timeout),
    do: GenServer.call(server, {:push, event, payload, timeout}, timeout + 1_000)

  def ready(server, payload \\ %{}), do: push(server, "agent.ready", payload)
  def heartbeat(server, payload \\ %{}), do: push(server, "agent.heartbeat", payload)
  def send_message(server, payload), do: push(server, "message.send", payload)
  def discover(server, payload), do: push(server, "agent.discover", payload)
  def create_task(server, payload), do: push(server, "task.create", payload)
  def rpc(server, payload), do: push(server, "rpc.request", payload)
  def subscribe_tasks(server, ids), do: subscribe(server, "task.subscribe", %{"task_ids" => ids})

  def subscribe_groups(server, ids),
    do: subscribe(server, "group.subscribe", %{"group_ids" => ids})

  def subscribe_presence(server, ids),
    do: subscribe(server, "presence.subscribe", %{"service_agent_ids" => ids})

  def subscribe_queue(server), do: subscribe(server, "queue.subscribe", %{})

  defp subscribe(server, event, payload),
    do: GenServer.call(server, {:subscribe, event, payload}, @default_timeout + 1_000)

  @impl true
  def init({opts, caller}) do
    provider =
      opts[:token_provider] ||
        static_provider(
          Keyword.fetch!(opts, :socket_token),
          Keyword.fetch!(opts, :service_agent_id)
        )

    state = %__MODULE__{
      base_url: opts[:base_url] || "https://robotscenter.net",
      token_provider: provider,
      join_payload: opts[:join_payload] || %{},
      owner: opts[:owner] || caller
    }

    send(self(), :connect)
    {:ok, state}
  end

  @impl true
  def handle_call({:push, _event, _payload, _timeout}, _from, %{channel: nil} = state),
    do: {:reply, {:error, %RealtimeError{message: "realtime channel is not connected"}}, state}

  def handle_call({:push, event, payload, timeout}, _from, state),
    do: {:reply, checked_push(state.channel, event, payload, timeout), state}

  def handle_call({:subscribe, _event, _payload}, _from, %{channel: nil} = state),
    do: {:reply, {:error, %RealtimeError{message: "realtime channel is not connected"}}, state}

  def handle_call({:subscribe, event, payload}, _from, state) do
    key = {event, :erlang.phash2(payload)}

    case checked_push(state.channel, event, payload, @default_timeout) do
      {:ok, response} ->
        {:reply, {:ok, response},
         %{state | subscriptions: Map.put(state.subscriptions, key, {event, payload})}}

      error ->
        {:reply, error, state}
    end
  end

  @impl true
  def handle_info(:connect, %{stopping: false} = state) do
    state = cancel_timer(state, :reconnect_timer)

    case connect(state) do
      {:ok, connected} ->
        send(state.owner, {:robots_center_realtime, :connected})
        timer = Process.send_after(self(), :heartbeat, @heartbeat_interval)
        {:noreply, %{connected | reconnect_attempt: 0, heartbeat_timer: timer}}

      {:error, reason} ->
        send(state.owner, {:robots_center_realtime, {:error, reason}})
        {:noreply, schedule_reconnect(state)}
    end
  end

  def handle_info(:heartbeat, %{channel: channel, stopping: false} = state)
      when is_pid(channel) do
    PhoenixClient.Channel.push_async(channel, "agent.heartbeat", %{})

    {:noreply,
     %{state | heartbeat_timer: Process.send_after(self(), :heartbeat, @heartbeat_interval)}}
  end

  def handle_info(%Message{event: event, payload: payload}, state) do
    send(state.owner, {:robots_center_realtime, event, payload})
    {:noreply, state}
  end

  def handle_info({:EXIT, pid, reason}, %{stopping: false} = state)
      when pid == state.socket or pid == state.channel do
    send(state.owner, {:robots_center_realtime, :disconnected, reason})
    {:noreply, state |> disconnect() |> schedule_reconnect()}
  end

  def handle_info(_message, state), do: {:noreply, state}

  @impl true
  def terminate(_reason, state) do
    state
    |> Map.put(:stopping, true)
    |> cancel_timer(:heartbeat_timer)
    |> cancel_timer(:reconnect_timer)
    |> disconnect()

    :ok
  end

  defp connect(state) do
    Process.flag(:trap_exit, true)

    with {:ok, token} <- fetch_token(state.token_provider),
         {:ok, socket} <-
           PhoenixClient.Socket.start_link(
             url: socket_url(state.base_url),
             params: %{"socket_token" => token.socket_token},
             reconnect?: false,
             heartbeat_interval: @heartbeat_interval
           ),
         :ok <- await_connected(socket, 100),
         {:ok, _reply, channel} <-
           PhoenixClient.Channel.join(
             socket,
             "agent:#{token.service_agent_id}",
             state.join_payload
           ) do
      Enum.each(state.subscriptions, fn {_key, {event, payload}} ->
        PhoenixClient.Channel.push_async(channel, event, payload)
      end)

      {:ok, %{state | socket: socket, channel: channel}}
    end
  end

  defp fetch_token(provider) do
    case provider.() do
      {:ok, token} -> normalize_token(token)
      token when is_map(token) -> normalize_token(token)
      {:error, reason} -> {:error, reason}
      other -> {:error, {:invalid_token_provider_result, other}}
    end
  end

  defp normalize_token(token) do
    socket_token = token[:socket_token] || token["socket_token"]
    service_agent_id = token[:service_agent_id] || token["service_agent_id"]

    if is_binary(socket_token) and is_binary(service_agent_id),
      do: {:ok, %{socket_token: socket_token, service_agent_id: service_agent_id}},
      else: {:error, :invalid_socket_token}
  end

  defp static_provider(socket_token, service_agent_id),
    do: fn -> %{socket_token: socket_token, service_agent_id: service_agent_id} end

  defp channel_push(channel, event, payload, timeout) do
    case PhoenixClient.Channel.push(channel, event, payload, timeout) do
      {:ok, response} ->
        {:ok, response}

      {:error, reason} ->
        {:error, %RealtimeError{message: "#{event} failed: #{inspect(reason)}", details: reason}}

      {:timeout, reason} ->
        {:error, %RealtimeError{message: "#{event} timed out", details: reason}}
    end
  end

  defp checked_push(channel, event, payload, timeout) do
    if byte_size(Jason.encode!([nil, nil, "agent", event, payload])) > 65_536,
      do: {:error, %RealtimeError{message: "Phoenix frame exceeds the 64 KiB payload limit"}},
      else: channel_push(channel, event, payload, timeout)
  end

  defp await_connected(_socket, 0), do: {:error, :connect_timeout}

  defp await_connected(socket, attempts) do
    if PhoenixClient.Socket.connected?(socket),
      do: :ok,
      else:
        (
          Process.sleep(50)
          await_connected(socket, attempts - 1)
        )
  end

  defp schedule_reconnect(%{stopping: true} = state), do: state

  defp schedule_reconnect(%{reconnect_timer: nil} = state) do
    timer = Process.send_after(self(), :connect, reconnect_delay(state.reconnect_attempt))
    %{state | reconnect_timer: timer, reconnect_attempt: state.reconnect_attempt + 1}
  end

  defp schedule_reconnect(state), do: state

  defp reconnect_delay(attempt) do
    base = Enum.at(@backoff, min(attempt, length(@backoff) - 1))
    round(base * (0.8 + :rand.uniform() * 0.4))
  end

  defp cancel_timer(state, field) do
    if timer = Map.get(state, field), do: Process.cancel_timer(timer)
    Map.put(state, field, nil)
  end

  defp disconnect(state) do
    state = cancel_timer(state, :heartbeat_timer)

    if state.channel && Process.alive?(state.channel),
      do: PhoenixClient.Channel.leave(state.channel)

    if state.socket && Process.alive?(state.socket), do: PhoenixClient.Socket.stop(state.socket)
    %{state | socket: nil, channel: nil}
  end

  defp socket_url(base_url) do
    uri = URI.parse(base_url)

    %{
      uri
      | scheme: if(uri.scheme == "https", do: "wss", else: "ws"),
        path: String.trim_trailing(uri.path || "", "/") <> "/socket/websocket"
    }
    |> URI.to_string()
  end
end
