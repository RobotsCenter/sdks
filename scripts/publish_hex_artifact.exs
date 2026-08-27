Mix.start()
Mix.Local.append_archives()

path = System.fetch_env!("HEX_PACKAGE_PATH")
tarball = File.read!(path)

case Hex.API.Release.publish(nil, tarball, [], fn _ -> nil end, false) do
  {:ok, {status, _headers, body}} when status in 200..299 ->
    location = body["html_url"] || body["url"] || "Hex.pm"
    IO.puts("Published immutable package artifact to #{location}")

  other ->
    raise "Hex package publication failed: #{inspect(other)}"
end
