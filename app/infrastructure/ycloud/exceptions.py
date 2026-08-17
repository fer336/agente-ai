class YCloudAPIError(Exception):
    """Raised when the YCloud REST API returns a non-2xx response.

    `status_code` is optional (defaults to `None`) rather than required —
    unlike Dentalink's `DentalinkAPIError`, not every raise site here has
    one readily available (`YCloudHandoffGateway`'s own raise predates this
    field and does not pass it); callers that DO know it (`YCloudClient`)
    should still pass it, since it feeds `tool_executions.http_status`
    (PRD.md §41) when available.
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)
