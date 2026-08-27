defmodule RobotsCenter.ClientTest do
  use ExUnit.Case, async: true

  alias RobotsCenter.Client

  test "constructs a client with safe defaults" do
    client = Client.new(token: "agk_test")
    assert client.token == "agk_test"
    assert client.base_url == "https://robotscenter.net"
    assert client.max_retries == 3
  end

  test "trims the base URL" do
    assert Client.new(token: "test", base_url: "https://example.test/").base_url ==
             "https://example.test"
  end
end

defmodule RobotsCenter.RealtimeTest do
  use ExUnit.Case, async: true

  test "token-provider failure is reported to the caller and explicit reconnect false has no timer" do
    {:ok, pid} =
      RobotsCenter.Realtime.start_link(
        token_provider: fn -> {:error, :unauthorized} end,
        reconnect: false
      )

    assert_receive {:robots_center_realtime, {:error, :unauthorized}}, 1_000
    state = :sys.get_state(pid)
    assert state.owner == self()
    assert state.reconnect_timer == nil
    RobotsCenter.Realtime.close(pid)
  end

  test "oversized frames are rejected before transport" do
    state = %RobotsCenter.Realtime{channel: self()}

    {:reply, {:error, error}, ^state} =
      RobotsCenter.Realtime.handle_call(
        {:push, "event", %{"body" => String.duplicate("x", 66_000)}, 100},
        {self(), make_ref()},
        state
      )

    assert error.message =~ "64 KiB"
  end
end
