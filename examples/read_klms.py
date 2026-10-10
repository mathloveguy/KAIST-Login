"""Run using the Python environment where kaist-login is installed."""
import asyncio
from kaist_login.browser import Broker
from kaist_login.errors import BrokerError


async def main():
    try:
        result = await Broker().read("klms")
        print(result["text"])
    except BrokerError as error:
        print(error.code)
    except Exception:
        # Never print raw browser exceptions: a fill() error can contain a secret.
        print("operation_failed")


asyncio.run(main())
