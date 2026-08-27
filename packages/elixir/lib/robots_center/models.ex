defmodule RobotsCenter.Problem do
  @moduledoc "RFC 9457 problem response."
  defstruct [:type, :title, :status, :detail, :instance, :code, errors: %{}]
end

defmodule RobotsCenter.Agent do
  @moduledoc "Service-agent response."
  defstruct [
    :id,
    :name,
    :framework,
    :framework_version,
    :description,
    capabilities: [],
    metadata: %{}
  ]
end

defmodule RobotsCenter.Message do
  @moduledoc "Cross-agent message envelope."
  defstruct [
    :message_id,
    :message_type,
    :recipient,
    :sender,
    :conversation_id,
    :correlation_id,
    :status,
    payload: %{}
  ]
end

defmodule RobotsCenter.Task do
  @moduledoc "Delegated agent task."
  defstruct [:task_id, :status, :priority, :operation, :input, :result, :error]
end

defmodule RobotsCenter.Group do
  @moduledoc "Agent group."
  defstruct [:id, :name, :description, members: [], metadata: %{}]
end

defmodule RobotsCenter.SocketToken do
  @moduledoc "Short-lived Phoenix socket credential."
  defstruct [
    :socket_token,
    :expires_in,
    :workspace_id,
    :service_agent_id,
    :socket_path,
    scopes: []
  ]
end
