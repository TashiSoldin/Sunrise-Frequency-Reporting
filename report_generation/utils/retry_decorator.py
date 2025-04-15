import functools
import logging
import time
from typing import Callable, Union

logger = logging.getLogger(__name__)


def retry(
    max_attempts: int = 3,
    delay: int = 5,
    backoff: int = 2,
    exceptions: Union[Exception, list[Exception]] = Exception,
) -> Callable:
    """
    Retry decorator with exponential backoff for functions.

    Args:
        max_attempts: Maximum number of retry attempts
        delay: Initial delay between retries in seconds
        backoff: Backoff multiplier
        exceptions: Exception(s) to catch and retry on

    Returns:
        Decorated function with retry logic
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            attempt = 1
            current_delay = delay

            while attempt <= max_attempts:
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_attempts:
                        logger.error(f"Failed after {max_attempts} attempts: {str(e)}")
                        raise

                    logger.warning(
                        f"Attempt {attempt} failed: {str(e)}. "
                        f"Retrying in {current_delay} seconds..."
                    )
                    time.sleep(current_delay)
                    current_delay *= backoff
                    attempt += 1

        return wrapper

    return decorator
