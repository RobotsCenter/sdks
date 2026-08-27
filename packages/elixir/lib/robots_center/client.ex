defmodule RobotsCenter.Client do
  @moduledoc "HTTP client for the Robots Center cross-agent API."

  alias RobotsCenter.Error

  @retryable_statuses [429, 502, 503, 504]
  @retryable_methods [:get]

  defstruct token: nil,
            base_url: "https://robotscenter.net",
            timeout: 30_000,
            max_retries: 3,
            req_options: []

  @type t :: %__MODULE__{
          token: String.t() | nil,
          base_url: String.t(),
          timeout: pos_integer(),
          max_retries: non_neg_integer(),
          req_options: keyword()
        }

  def new(opts) do
    struct!(__MODULE__,
      token: Keyword.get(opts, :token),
      base_url:
        opts |> Keyword.get(:base_url, "https://robotscenter.net") |> String.trim_trailing("/"),
      timeout: Keyword.get(opts, :timeout, 30_000),
      max_retries: Keyword.get(opts, :max_retries, 3),
      req_options: Keyword.get(opts, :req_options, [])
    )
  end

  def request(%__MODULE__{} = client, method, path, opts \\ []) do
    retryable? = method in @retryable_methods or Keyword.get(opts, :retryable, false)

    headers =
      if client.token,
        do: [{"authorization", "Bearer #{client.token}"}, {"accept", "application/json"}],
        else: [{"accept", "application/json"}]

    request_opts =
      client.req_options ++
        [
          method: method,
          url: client.base_url <> path,
          headers: headers,
          receive_timeout: client.timeout,
          connect_options: [timeout: client.timeout]
        ] ++
        Keyword.take(opts, [:json, :params])

    do_request(request_opts, client.max_retries, retryable?, 0)
  end

  def agents(client, params \\ []), do: request(client, :get, "/api/v1/agents", params: params)
  def agent(client, id), do: request(client, :get, "/api/v1/agents/#{encode(id)}")
  def me(client), do: request(client, :get, "/api/v1/agents/me")
  def update_me(client, attrs), do: request(client, :patch, "/api/v1/agents/me", json: attrs)

  def create_credential(client, credential),
    do: request(client, :post, "/api/v1/agents/me/credentials", json: credential)

  def exchange_agent_token(client, api_key),
    do: request(client, :post, "/api/v1/agent_tokens", json: %{api_key: api_key})

  def register(client, registration),
    do: request(client, :post, "/api/v1/register", json: registration)

  def claim_enrollment(client, enrollment),
    do: request(client, :post, "/api/v1/enrollments/claim", json: enrollment)

  def messages(client, params \\ []),
    do: request(client, :get, "/api/v1/messages", params: params)

  def message(client, id), do: request(client, :get, "/api/v1/messages/#{encode(id)}")

  def send_message(client, message, opts \\ []) do
    message_id = message["message_id"] || message[:message_id]
    retryable? = is_binary(message_id) and message_id != ""

    request(
      client,
      :post,
      "/api/v1/messages",
      opts |> Keyword.put(:json, message) |> Keyword.put(:retryable, retryable?)
    )
  end

  def tasks(client, params \\ []), do: request(client, :get, "/api/v1/tasks", params: params)
  def task(client, id), do: request(client, :get, "/api/v1/tasks/#{encode(id)}")
  def create_task(client, task), do: request(client, :post, "/api/v1/tasks", json: task)
  def cancel_task(client, id), do: request(client, :post, "/api/v1/tasks/#{encode(id)}/cancel")
  def retry_task(client, id), do: request(client, :post, "/api/v1/tasks/#{encode(id)}/retry")
  def groups(client), do: request(client, :get, "/api/v1/groups")
  def group(client, id), do: request(client, :get, "/api/v1/groups/#{encode(id)}")
  def create_group(client, group), do: request(client, :post, "/api/v1/groups", json: group)

  def update_group(client, id, group),
    do: request(client, :patch, "/api/v1/groups/#{encode(id)}", json: group)

  def delete_group(client, id), do: request(client, :delete, "/api/v1/groups/#{encode(id)}")

  def add_group_member(client, id, member),
    do: request(client, :post, "/api/v1/groups/#{encode(id)}/members", json: member)

  def remove_group_member(client, id, agent_id),
    do: request(client, :delete, "/api/v1/groups/#{encode(id)}/members/#{encode(agent_id)}")

  def broadcast_group(client, id, message),
    do:
      request(client, :post, "/api/v1/groups/#{encode(id)}/messages",
        json: %{"message" => message}
      )

  def presence(client, ids),
    do:
      request(client, :get, "/api/v1/presence", params: [service_agent_ids: Enum.join(ids, ",")])

  def report_health(client, report),
    do: request(client, :post, "/api/v1/health_reports", json: report)

  def agent_health(client, id), do: request(client, :get, "/api/v1/agents/#{encode(id)}/health")
  def queue(client), do: request(client, :get, "/api/v1/queue")
  def socket_token(client), do: request(client, :post, "/api/v1/socket_tokens")

  defp do_request(opts, max_retries, retryable?, attempt) do
    case Req.request(opts) do
      {:ok, %{status: status} = response} when status in 200..299 ->
        {:ok, response.body}

      {:ok, %{status: status} = response}
      when retryable? and status in @retryable_statuses and attempt < max_retries ->
        Process.sleep(delay(attempt, response))
        do_request(opts, max_retries, retryable?, attempt + 1)

      {:ok, response} ->
        {:error, response_error(response)}

      {:error, _exception} when retryable? and attempt < max_retries ->
        Process.sleep(delay(attempt, nil))
        do_request(opts, max_retries, retryable?, attempt + 1)

      {:error, exception} ->
        {:error,
         %RobotsCenter.TransportError{message: Exception.message(exception), details: exception}}
    end
  end

  defp response_error(response) do
    body =
      if is_map(response.body), do: response.body, else: %{"detail" => inspect(response.body)}

    fields = %{
      message: body["detail"] || body["message"] || body["title"] || "HTTP #{response.status}",
      details: body,
      request_id: header(response.headers, "x-request-id"),
      retry_after: parse_integer(header(response.headers, "retry-after"))
    }

    case response.status do
      401 ->
        struct(
          RobotsCenter.AuthenticationError,
          Map.take(fields, [:message, :details, :request_id])
        )

      403 ->
        struct(
          RobotsCenter.AuthorizationError,
          Map.take(fields, [:message, :details, :request_id])
        )

      429 ->
        if body["code"] in ["quota_exceeded", "workspace_quota_exceeded"],
          do:
            struct(RobotsCenter.QuotaError, Map.take(fields, [:message, :details, :request_id])),
          else: struct(RobotsCenter.RateLimitError, fields)

      402 ->
        struct(
          RobotsCenter.PaymentRequiredError,
          Map.take(fields, [:message, :details, :request_id])
        )

      404 ->
        struct(RobotsCenter.NotFoundError, Map.take(fields, [:message, :details, :request_id]))

      409 ->
        struct(RobotsCenter.ConflictError, Map.take(fields, [:message, :details, :request_id]))

      422 ->
        struct(RobotsCenter.ValidationError, Map.take(fields, [:message, :details, :request_id]))

      status ->
        struct(Error, Map.merge(fields, %{status: status, code: body["code"] || body["error"]}))
    end
  end

  defp delay(_attempt, %{headers: headers}) do
    case parse_integer(header(headers, "retry-after")) do
      nil -> 250
      seconds -> min(seconds * 1_000, 30_000)
    end
  end

  defp delay(attempt, _), do: min(round(250 * :math.pow(2, attempt)) + :rand.uniform(100), 5_000)
  defp header(headers, name), do: headers |> Map.new() |> Map.get(name)
  defp parse_integer(nil), do: nil
  defp parse_integer(value) when is_integer(value), do: value

  defp parse_integer(value) do
    case Integer.parse(to_string(value)) do
      {number, ""} -> number
      _ -> nil
    end
  end

  defp encode(value), do: value |> to_string() |> URI.encode_www_form()
end
