export class RobotsCenterError extends Error {
  override readonly name: string = "RobotsCenterError";
}

export class TransportError extends RobotsCenterError {
  override readonly name = "TransportError";
}

export class RealtimeError extends RobotsCenterError {
  override readonly name = "RealtimeError";
  constructor(message: string, readonly terminal = false) { super(message); }
}

export class ApiError extends RobotsCenterError {
  override readonly name: string = "ApiError";
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
    readonly details?: unknown,
    readonly requestId?: string,
  ) {
    super(message);
  }
}

export class AuthenticationError extends ApiError {
  override readonly name = "AuthenticationError";
}

export class AuthorizationError extends ApiError {
  override readonly name = "AuthorizationError";
}

export class RateLimitError extends ApiError {
  override readonly name = "RateLimitError";
  constructor(message: string, status: number, code?: string, details?: unknown, requestId?: string, readonly retryAfter?: number) {
    super(message, status, code, details, requestId);
  }
}
export class QuotaError extends ApiError { override readonly name = "QuotaError"; }
export class PaymentRequiredError extends ApiError { override readonly name = "PaymentRequiredError"; }
export class NotFoundError extends ApiError { override readonly name = "NotFoundError"; }
export class ConflictError extends ApiError { override readonly name = "ConflictError"; }
export class ValidationError extends ApiError { override readonly name = "ValidationError"; }
