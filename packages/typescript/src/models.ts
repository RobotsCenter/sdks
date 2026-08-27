import type {Json} from "./client.js";

export interface Problem {
  type?: string;
  title: string;
  status: number;
  detail?: string;
  instance?: string;
  code?: string;
  errors?: Record<string, Json>;
}

export interface Agent {
  id: string;
  name: string;
  capabilities: string[];
  framework?: string | null;
  framework_version?: string | null;
  description?: string | null;
  metadata?: Record<string, Json>;
}

export interface Message {
  message_id: string;
  message_type: string;
  payload: Record<string, Json>;
  recipient: Record<string, Json>;
  sender?: Record<string, Json>;
  conversation_id?: string | null;
  correlation_id?: string | null;
  status?: string;
}

export interface Task {
  task_id: string;
  status: string;
  priority: string;
  operation?: string;
  input_data?: Record<string, Json>;
  result?: Record<string, Json> | null;
  error?: Record<string, Json> | null;
}

export interface Group {
  group_id: string;
  name: string;
  description?: string | null;
  members?: Array<Record<string, Json>>;
  metadata?: Record<string, Json>;
}
