defmodule RobotsCenter.Test.FakeSocket do
  use GenServer

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts)
  def connected?(pid), do: GenServer.call(pid, :connected?)
  def push(pid, message), do: GenServer.call(pid, {:push, message})
  def stop(pid), do: GenServer.stop(pid, :normal)
  def settings(pid), do: GenServer.call(pid, :settings)

  @impl true
  def init(opts) do
    test_pid = Keyword.fetch!(opts, :test_pid)
    send(test_pid, {:fake_socket_started, self(), opts})
    {:ok, %{test_pid: test_pid, opts: opts}}
  end

  @impl true
  def handle_call(:connected?, _from, state), do: {:reply, true, state}
  def handle_call(:settings, _from, state), do: {:reply, state, state}

  def handle_call({:push, message}, _from, state) do
    send(state.test_pid, {:fake_socket_push, self(), message})
    {:reply, :ok, state}
  end

  @impl true
  def terminate(reason, state) do
    send(state.test_pid, {:fake_socket_stopped, self(), reason})
    :ok
  end
end

defmodule RobotsCenter.Test.FakeChannel do
  use GenServer

  def join(socket, topic, payload) do
    settings = RobotsCenter.Test.FakeSocket.settings(socket)
    test_pid = settings.test_pid
    send(test_pid, {:fake_channel_join, socket, topic, payload})

    case Keyword.get(settings.opts, :join_result, :ok) do
      :ok ->
        {:ok, channel} = GenServer.start_link(__MODULE__, {test_pid, topic})
        {:ok, %{}, channel}

      {:error, reason} ->
        {:error, reason}
    end
  end

  def push(pid, event, payload, _timeout), do: GenServer.call(pid, {:push, event, payload})
  def push_async(pid, event, payload), do: GenServer.cast(pid, {:push, event, payload})

  def leave(pid) do
    if Process.alive?(pid), do: GenServer.stop(pid, :normal)
    :ok
  end

  @impl true
  def init({test_pid, topic}), do: {:ok, %{test_pid: test_pid, topic: topic}}

  @impl true
  def handle_call({:push, event, payload}, _from, state) do
    send(state.test_pid, {:fake_channel_push, self(), event, payload})
    {:reply, {:ok, %{"status" => "ok"}}, state}
  end

  @impl true
  def handle_cast({:push, event, payload}, state) do
    send(state.test_pid, {:fake_channel_push_async, self(), event, payload})
    {:noreply, state}
  end

  @impl true
  def terminate(reason, state) do
    send(state.test_pid, {:fake_channel_stopped, self(), reason})
    :ok
  end
end

defmodule RobotsCenter.RealtimeLifecycleTest do
  use ExUnit.Case, async: false

  alias PhoenixClient.Message
  alias RobotsCenter.{Realtime, RealtimeError}
  alias RobotsCenter.Test.{FakeChannel, FakeSocket}

  defp start_realtime(opts) do
    defaults = [
      owner: self(),
      socket_module: FakeSocket,
      channel_module: FakeChannel,
      socket_options: [test_pid: self()],
      socket_token: "static-token",
      service_agent_id: "agent-1",
      reconnect: false
    ]

    {:ok, pid} = Realtime.start_link(Keyword.merge(defaults, opts))
    pid
  end

  defp await_connection do
    assert_receive {:fake_socket_started, socket, opts}, 1_000
    assert_receive {:fake_channel_join, ^socket, topic, payload}, 1_000
    assert_receive {:robots_center_realtime, :connected}, 1_000
    %{socket: socket, topic: topic, payload: payload, opts: opts}
  end

  test "static credentials cannot opt into reconnect" do
    Process.flag(:trap_exit, true)

    assert {:error, {%ArgumentError{message: message}, _stacktrace}} =
             Realtime.start_link(
               socket_token: "static-token",
               service_agent_id: "agent-1",
               reconnect: true
             )

    assert message =~ "reconnect requires token_provider"
  end

  test "terminal channel close and terminal linked-process exits never reconnect" do
    for {event, reason} <- [
          {"phx_close", %{"reason" => "workspace_archived"}},
          {"phx_error", %{"reason" => "unauthorized"}}
        ] do
      tokens = Agent.start_link(fn -> 0 end) |> elem(1)
      provider = token_provider(tokens)
      realtime = start_realtime(token_provider: provider, reconnect: true, reconnect_delays: [5])
      %{socket: socket} = await_connection()

      send(realtime, %Message{event: event, payload: reason})
      assert_receive {:robots_center_realtime, :disconnected, ^reason}
      assert_receive {:fake_socket_stopped, ^socket, :normal}
      refute_receive {:fake_socket_started, _, _}, 50
      GenServer.stop(realtime)
    end

    tokens = Agent.start_link(fn -> 0 end) |> elem(1)

    realtime =
      start_realtime(
        token_provider: token_provider(tokens),
        reconnect: true,
        reconnect_delays: [5]
      )

    await_connection()
    state = :sys.get_state(realtime)
    Process.exit(state.channel, :workspace_frozen)
    assert_receive {:robots_center_realtime, :disconnected, :workspace_frozen}
    refute_receive {:fake_socket_started, _, _}, 50
  end

  test "transient disconnect reconnects with a fresh token and replays subscriptions" do
    counter = Agent.start_link(fn -> 0 end) |> elem(1)

    realtime =
      start_realtime(
        token_provider: token_provider(counter),
        reconnect: true,
        reconnect_delays: [5]
      )

    first = await_connection()
    assert get_in(first.opts, [:params, "socket_token"]) == "token-1"
    assert {:ok, _} = Realtime.subscribe_presence(realtime, ["a", "b"])

    assert_receive {:fake_channel_push, _, "presence.subscribe",
                    %{"service_agent_ids" => ["a", "b"]}}

    assert {:ok, _} = Realtime.unsubscribe_presence(realtime, ["a"])

    assert_receive {:fake_channel_push, _, "presence.unsubscribe",
                    %{"service_agent_ids" => ["a"]}}

    send(realtime, %Message{event: "phx_error", payload: %{"reason" => "transport_closed"}})
    assert_receive {:robots_center_realtime, :disconnected, _}
    second = await_connection()
    assert get_in(second.opts, [:params, "socket_token"]) == "token-2"
    assert_receive {:fake_channel_push, _, "presence.subscribe", %{"service_agent_ids" => ["b"]}}
  end

  test "explicit disconnect cancels heartbeat and suppresses reconnect" do
    counter = Agent.start_link(fn -> 0 end) |> elem(1)

    realtime =
      start_realtime(
        token_provider: token_provider(counter),
        reconnect: true,
        reconnect_delays: [5]
      )

    %{socket: socket} = await_connection()
    assert :ok = Realtime.disconnect(realtime)
    assert_receive {:fake_socket_stopped, ^socket, :normal}
    refute_receive {:fake_socket_started, _, _}, 50
    assert {:error, %RealtimeError{}} = Realtime.ready(realtime)
  end

  test "sends Phoenix transport and agent heartbeats every configured interval" do
    realtime = start_realtime(heartbeat_interval: 10)
    %{socket: socket} = await_connection()

    assert_receive {:fake_socket_push, ^socket,
                    %Message{topic: "phoenix", event: "heartbeat", payload: %{}}},
                   200

    assert_receive {:fake_channel_push_async, _, "agent.heartbeat", %{}}, 200
    assert Process.alive?(realtime)
  end

  test "full-frame size checks use the actual topic and conservative refs" do
    realtime = start_realtime(service_agent_id: String.duplicate("agent", 20))
    %{topic: topic} = await_connection()
    event = "message.send"

    allowed = boundary_payload(topic, event, 65_536)
    rejected = %{"data" => allowed["data"] <> "x"}
    assert frame_size(topic, event, allowed) <= 65_536
    assert frame_size(topic, event, rejected) > 65_536

    assert {:ok, _} = Realtime.push(realtime, event, allowed)
    assert_receive {:fake_channel_push, _, ^event, ^allowed}

    assert {:error, %RealtimeError{message: message}} = Realtime.push(realtime, event, rejected)
    assert message =~ "64 KiB"
    refute_receive {:fake_channel_push, _, ^event, ^rejected}, 20
  end

  test "oversized joins and failed joins stop their socket before reconnecting" do
    topic = "agent:agent-1"
    join_payload = boundary_join_payload(topic, 65_537)
    realtime = start_realtime(join_payload: join_payload)
    assert_receive {:fake_socket_started, socket, _}
    assert_receive {:fake_socket_stopped, ^socket, :normal}
    assert_receive {:robots_center_realtime, {:error, :payload_too_large}}
    refute_receive {:fake_channel_join, _, _, _}, 20
    GenServer.stop(realtime)

    realtime = start_realtime(socket_options: [test_pid: self(), join_result: {:error, :denied}])
    assert_receive {:fake_socket_started, socket, _}
    assert_receive {:fake_channel_join, ^socket, _, _}
    assert_receive {:fake_socket_stopped, ^socket, :normal}
    assert_receive {:robots_center_realtime, {:error, :denied}}
    refute Process.alive?(socket)
    GenServer.stop(realtime)
  end

  defp token_provider(counter) do
    fn ->
      value = Agent.get_and_update(counter, fn current -> {current + 1, current + 1} end)
      %{socket_token: "token-#{value}", service_agent_id: "agent-#{value}"}
    end
  end

  defp frame_size(topic, event, payload),
    do: byte_size(Jason.encode!(["1", "18446744073709551615", topic, event, payload]))

  defp boundary_payload(topic, event, target) do
    payload = %{"data" => ""}
    overhead = frame_size(topic, event, payload)
    %{"data" => String.duplicate("x", target - overhead)}
  end

  defp boundary_join_payload(topic, target) do
    empty = %{"data" => ""}
    overhead = byte_size(Jason.encode!([nil, "1", topic, "phx_join", empty]))
    %{"data" => String.duplicate("x", target - overhead)}
  end
end
