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
    :topic,
    :socket_module,
    :channel_module,
    :socket_options,
    heartbeat_interval: @heartbeat_interval,
    reconnect_delays: @backoff,
    subscriptions: %{},
    reconnect_attempt: 0,
    stopping: false,
    reconnect: false
  ]

  def start_link(opts), do: GenServer.start_link(__MODULE__, {opts, self()}, name: opts[:name])
  def close(server), do: GenServer.stop(server, :normal)
  def disconnect(server), do: GenServer.call(server, :disconnect)

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

  def acknowledge_message(server, id),
    do: push(server, "message.delivered", %{"message_id" => id})

  def complete_task(server, id, result \\ %{}, retry_count \\ 0),
    do:
      push(server, "task.complete", %{
        "task_id" => id,
        "result" => result,
        "retry_count" => retry_count
      })

  def fail_task(server, id, message, retry_count \\ 0),
    do:
      push(server, "task.fail", %{
        "task_id" => id,
        "error_message" => message,
        "retry_count" => retry_count
      })

  def cancel_task(server, id), do: push(server, "task.cancel", %{"task_id" => id})
  def retry_task(server, id), do: push(server, "task.retry", %{"task_id" => id})
  def create_group(server, group), do: push(server, "group.create", %{"group" => group})
  def list_groups(server), do: push(server, "group.list")

  def add_group_member(server, group_id, agent_id, role \\ "member"),
    do:
      push(server, "group.add_member", %{
        "group_id" => group_id,
        "service_agent_id" => agent_id,
        "role" => role
      })

  def remove_group_member(server, group_id, agent_id),
    do:
      push(server, "group.remove_member", %{
        "group_id" => group_id,
        "service_agent_id" => agent_id
      })

  def broadcast_group(server, group_id, message),
    do: push(server, "group.broadcast", %{"group_id" => group_id, "message" => message})

  def unsubscribe_presence(server, ids),
    do:
      GenServer.call(
        server,
        {:unsubscribe, "presence.subscribe", "presence.unsubscribe",
         %{"service_agent_ids" => ids}},
        @default_timeout + 1_000
      )

  def report_health(server, metrics), do: push(server, "health.report", %{"metrics" => metrics})

  def rpc_response(server, id, result),
    do: push(server, "rpc.response", %{"correlation_id" => id, "result" => result})

  def queue_stats(server), do: push(server, "queue.stats")

  def unsubscribe_queue(server),
    do:
      GenServer.call(
        server,
        {:unsubscribe, "queue.subscribe", "queue.unsubscribe", %{}},
        @default_timeout + 1_000
      )

  def command_accepted(server, id, result \\ %{}),
    do: push(server, "command.accepted", %{"command_id" => id, "result_payload" => result})

  def command_progress(server, id, result),
    do: push(server, "command.progress", %{"command_id" => id, "result_payload" => result})

  def command_complete(server, id, result \\ %{}, status \\ "succeeded"),
    do:
      push(server, "command.complete", %{
        "command_id" => id,
        "result_payload" => result,
        "status" => status
      })

  def command_fail(server, id, error, status \\ "failed"),
    do:
      push(server, "command.fail", %{
        "command_id" => id,
        "error_payload" => error,
        "status" => status
      })

  defp subscribe(server, event, payload),
    do: GenServer.call(server, {:subscribe, event, payload}, @default_timeout + 1_000)

  @impl true
  def init({opts, caller}) do
    if is_nil(opts[:token_provider]) and opts[:reconnect] == true,
      do:
        raise(
          ArgumentError,
          "reconnect requires token_provider so expired socket tokens are never reused"
        )

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
      owner: opts[:owner] || caller,
      socket_module: opts[:socket_module] || PhoenixClient.Socket,
      channel_module: opts[:channel_module] || PhoenixClient.Channel,
      socket_options: opts[:socket_options] || [],
      heartbeat_interval: opts[:heartbeat_interval] || @heartbeat_interval,
      reconnect_delays: opts[:reconnect_delays] || @backoff,
      reconnect: Keyword.get(opts, :reconnect, not is_nil(opts[:token_provider]))
    }

    send(self(), :connect)
    {:ok, state}
  end

  @impl true
  def handle_call({:push, _event, _payload, _timeout}, _from, %{channel: nil} = state),
    do: {:reply, {:error, %RealtimeError{message: "realtime channel is not connected"}}, state}

  def handle_call({:push, event, payload, timeout}, _from, state),
    do: {:reply, checked_push(state, event, payload, timeout), state}

  def handle_call(:disconnect, _from, state) do
    state = %{state | stopping: true, reconnect: false}
    {:reply, :ok, disconnect_connection(state)}
  end

  def handle_call({:subscribe, _event, _payload}, _from, %{channel: nil} = state),
    do: {:reply, {:error, %RealtimeError{message: "realtime channel is not connected"}}, state}

  def handle_call({:subscribe, event, payload}, _from, state) do
    key = {event, :erlang.phash2(payload)}

    case checked_push(state, event, payload, @default_timeout) do
      {:ok, response} ->
        {:reply, {:ok, response},
         %{state | subscriptions: Map.put(state.subscriptions, key, {event, payload})}}

      error ->
        {:reply, error, state}
    end
  end

  def handle_call({:unsubscribe, subscription_event, event, payload}, _from, state) do
    case checked_push(state, event, payload, @default_timeout) do
      {:ok, response} ->
        subscriptions = remove_subscription(state.subscriptions, subscription_event, payload)

        {:reply, {:ok, response}, %{state | subscriptions: subscriptions}}

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
        timer = Process.send_after(self(), :heartbeat, connected.heartbeat_interval)
        {:noreply, %{connected | reconnect_attempt: 0, heartbeat_timer: timer}}

      {:error, reason} ->
        send(state.owner, {:robots_center_realtime, {:error, reason}})

        if terminal_reason?(reason),
          do: {:noreply, %{state | stopping: true}},
          else: {:noreply, schedule_reconnect(state)}
    end
  end

  def handle_info(:heartbeat, %{channel: channel, stopping: false} = state)
      when is_pid(channel) do
    if state.socket,
      do:
        state.socket_module.push(state.socket, %Message{
          topic: "phoenix",
          event: "heartbeat",
          payload: %{}
        })

    state.channel_module.push_async(channel, "agent.heartbeat", %{})

    {:noreply,
     %{
       state
       | heartbeat_timer: Process.send_after(self(), :heartbeat, state.heartbeat_interval)
     }}
  end

  def handle_info(%Message{event: event, payload: payload}, state) do
    if event in ["phx_error", "phx_close"] do
      send(state.owner, {:robots_center_realtime, :disconnected, payload})

      state = disconnect_connection(state)

      if terminal_reason?(payload),
        do: {:noreply, %{state | stopping: true}},
        else: {:noreply, schedule_reconnect(state)}
    else
      send(state.owner, {:robots_center_realtime, event, payload})
      {:noreply, state}
    end
  end

  def handle_info({:EXIT, pid, reason}, %{stopping: false} = state)
      when pid == state.socket or pid == state.channel do
    send(state.owner, {:robots_center_realtime, :disconnected, reason})
    state = disconnect_connection(state)

    if terminal_reason?(reason),
      do: {:noreply, %{state | stopping: true}},
      else: {:noreply, schedule_reconnect(state)}
  end

  def handle_info(_message, state), do: {:noreply, state}

  @impl true
  def terminate(_reason, state) do
    state
    |> Map.put(:stopping, true)
    |> cancel_timer(:heartbeat_timer)
    |> cancel_timer(:reconnect_timer)
    |> disconnect_connection()

    :ok
  end

  defp connect(state) do
    Process.flag(:trap_exit, true)

    with {:ok, token} <- fetch_token(state.token_provider) do
      socket_opts =
        [
          url: socket_url(state.base_url),
          params: %{"socket_token" => token.socket_token},
          reconnect?: false,
          heartbeat_interval: state.heartbeat_interval
        ] ++ state.socket_options

      case state.socket_module.start_link(socket_opts) do
        {:ok, socket} -> connect_channel(state, token, socket)
        error -> error
      end
    end
  end

  defp connect_channel(state, token, socket) do
    result =
      with :ok <- check_join_frame("agent:#{token.service_agent_id}", state.join_payload),
           :ok <- await_connected(state.socket_module, socket, 100),
           {:ok, _reply, channel} <-
             state.channel_module.join(
               socket,
               "agent:#{token.service_agent_id}",
               state.join_payload
             ) do
        replay =
          Enum.reduce_while(state.subscriptions, :ok, fn {_key, {event, payload}}, :ok ->
            replay_state = %{state | channel: channel, topic: "agent:#{token.service_agent_id}"}

            case checked_push(replay_state, event, payload, @default_timeout) do
              {:ok, _} -> {:cont, :ok}
              error -> {:halt, error}
            end
          end)

        if replay == :ok do
          {:ok,
           %{
             state
             | socket: socket,
               channel: channel,
               topic: "agent:#{token.service_agent_id}"
           }}
        else
          if Process.alive?(channel), do: state.channel_module.leave(channel)
          replay
        end
      end

    if match?({:error, _}, result) and Process.alive?(socket),
      do: state.socket_module.stop(socket)

    result
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

  defp channel_push(state, event, payload, timeout) do
    case state.channel_module.push(state.channel, event, payload, timeout) do
      {:ok, response} ->
        {:ok, response}

      {:error, reason} ->
        {:error, %RealtimeError{message: "#{event} failed: #{inspect(reason)}", details: reason}}

      {:timeout, reason} ->
        {:error, %RealtimeError{message: "#{event} timed out", details: reason}}
    end
  end

  defp checked_push(state, event, payload, timeout) do
    # PhoenixClient uses the join ref "1" on a fresh connection. The message
    # ref is conservatively budgeted at the widest unsigned 64-bit decimal ref.
    frame = ["1", "18446744073709551615", state.topic, event, payload]

    if byte_size(Jason.encode!(frame)) > 65_536,
      do: {:error, %RealtimeError{message: "Phoenix frame exceeds the 64 KiB payload limit"}},
      else: channel_push(state, event, payload, timeout)
  end

  defp check_join_frame(topic, payload) do
    if byte_size(Jason.encode!([nil, "1", topic, "phx_join", payload])) > 65_536,
      do: {:error, :payload_too_large},
      else: :ok
  end

  defp terminal_reason?(reason) do
    text = inspect(reason)

    Enum.any?(
      ~w(unauthorized workspace_frozen workspace_paused workspace_archived workspace_unavailable),
      &String.contains?(text, &1)
    )
  end

  defp remove_subscription(subscriptions, "presence.subscribe", %{"service_agent_ids" => removed}) do
    Enum.reduce(subscriptions, %{}, fn {key, {event, payload}}, acc ->
      if event == "presence.subscribe" do
        remaining = Enum.reject(payload["service_agent_ids"] || [], &(&1 in removed))

        if remaining == [],
          do: acc,
          else:
            Map.put(
              acc,
              {event, :erlang.phash2(remaining)},
              {event, Map.put(payload, "service_agent_ids", remaining)}
            )
      else
        Map.put(acc, key, {event, payload})
      end
    end)
  end

  defp remove_subscription(subscriptions, event, _payload),
    do: Map.reject(subscriptions, fn {_key, {name, _payload}} -> name == event end)

  defp await_connected(_socket_module, _socket, 0), do: {:error, :connect_timeout}

  defp await_connected(socket_module, socket, attempts) do
    if socket_module.connected?(socket),
      do: :ok,
      else:
        (
          Process.sleep(50)
          await_connected(socket_module, socket, attempts - 1)
        )
  end

  defp schedule_reconnect(%{stopping: true} = state), do: state
  defp schedule_reconnect(%{reconnect: false} = state), do: state

  defp schedule_reconnect(%{reconnect_timer: nil} = state) do
    timer = Process.send_after(self(), :connect, reconnect_delay(state))
    %{state | reconnect_timer: timer, reconnect_attempt: state.reconnect_attempt + 1}
  end

  defp schedule_reconnect(state), do: state

  defp reconnect_delay(state) do
    attempt = state.reconnect_attempt
    delays = state.reconnect_delays
    base = Enum.at(delays, min(attempt, length(delays) - 1))
    round(base * (0.8 + :rand.uniform() * 0.4))
  end

  defp cancel_timer(state, field) do
    if timer = Map.get(state, field), do: Process.cancel_timer(timer)
    Map.put(state, field, nil)
  end

  defp disconnect_connection(state) do
    state = cancel_timer(state, :heartbeat_timer)

    if state.channel && Process.alive?(state.channel),
      do: state.channel_module.leave(state.channel)

    if state.socket && Process.alive?(state.socket), do: state.socket_module.stop(state.socket)
    %{state | socket: nil, channel: nil, topic: nil}
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
