from functools import wraps


class BrokerError(Exception):
    """Only static, non-sensitive messages may cross the tool boundary."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def safe_errors(function):
    """The Python API has the same error boundary as CLI/MCP."""
    @wraps(function)
    async def wrapped(*args, **kwargs):
        try:
            return await function(*args, **kwargs)
        except BrokerError:
            raise
        except Exception:
            raise BrokerError("operation_failed") from None
    return wrapped
