import time
from functools import wraps
from logging import getLogger

logger = getLogger(__name__)


def log_execution_time(func):
    """
    A decorator that logs the execution time of the decorated function.

    This decorator wraps the given function and measures its execution time.
    It logs the function name and the time taken to execute in seconds.

    Args:
        func (callable): The function to be decorated.

    Returns:
        callable: A wrapper function that logs the execution time.

    Example:
        @log_execution_time
        def some_function():
            # Function implementation
            pass
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        """
        Wrapper function that measures and logs the execution time.

        Args:
            *args: Variable length argument list for the decorated function.
            **kwargs: Arbitrary keyword arguments for the decorated function.

        Returns:
            The result of the decorated function.
        """
        start_time = time.perf_counter()
        result = func(*args, **kwargs)
        end_time = time.perf_counter()
        execution_time = end_time - start_time
        logger.info(f"{func.__name__} took {execution_time:.6f} seconds")
        return result

    return wrapper
