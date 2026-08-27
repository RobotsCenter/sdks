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
