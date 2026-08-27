Mix.start()
Mix.Local.append_archives()

case Application.ensure_all_started(:hex) do
  {:ok, _applications} -> :ok
  {:error, reason} -> raise "Could not start the Hex runtime: #{inspect(reason)}"
end

api_key = Hex.State.get(:api_key) || raise "HEX_API_KEY is required for Hex publication"

if System.get_env("HEX_PUBLISH_SMOKE") == "true" do
  IO.puts("Hex runtime started and HEX_API_KEY was loaded; publication skipped")
  System.halt(0)
end

path = System.fetch_env!("HEX_PACKAGE_PATH")
tarball = File.read!(path)

case Hex.API.Release.publish(nil, tarball, [key: api_key], fn _ -> nil end, false) do
  {:ok, {status, _headers, body}} when status in 200..299 ->
    location = body["html_url"] || body["url"] || "Hex.pm"
    IO.puts("Published immutable package artifact to #{location}")

  other ->
    raise "Hex package publication failed: #{inspect(other)}"
end
