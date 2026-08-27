defmodule RobotsCenter.Error do
  @moduledoc "Structured HTTP or transport error returned by the SDK."
  defexception [:message, :status, :code, :details, :request_id, :retry_after]

  @type t :: %__MODULE__{
          message: String.t(),
          status: non_neg_integer() | nil,
          code: String.t() | nil,
          details: term(),
          request_id: String.t() | nil,
          retry_after: non_neg_integer() | nil
        }
end

defmodule RobotsCenter.AuthenticationError do
  @moduledoc "HTTP 401 authentication failure."
  defexception [:message, :details, :request_id]
end

defmodule RobotsCenter.AuthorizationError do
  @moduledoc "HTTP 403 authorization failure."
  defexception [:message, :details, :request_id]
end

defmodule RobotsCenter.RateLimitError do
  @moduledoc "HTTP 429 rate-limit response."
  defexception [:message, :details, :request_id, :retry_after]
end

defmodule RobotsCenter.QuotaError do
  defexception [:message, :details, :request_id]
end

defmodule RobotsCenter.TransportError do
  @moduledoc "Network transport failure."
  defexception [:message, :details]
end

defmodule RobotsCenter.RealtimeError do
  @moduledoc "Phoenix transport or channel failure."
  defexception [:message, :details]
end

defmodule RobotsCenter.PaymentRequiredError do
  defexception [:message, :details, :request_id]
end

defmodule RobotsCenter.NotFoundError do
  defexception [:message, :details, :request_id]
end

defmodule RobotsCenter.ConflictError do
  defexception [:message, :details, :request_id]
end

defmodule RobotsCenter.ValidationError do
  defexception [:message, :details, :request_id]
end
