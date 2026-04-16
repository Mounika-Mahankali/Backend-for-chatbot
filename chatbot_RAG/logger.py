import time
import logging
from functools import wraps
from datetime import datetime

logger = logging.getLogger("RAGLogger")
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def log_execution(function_name):
    def decorator(func):

        @wraps(func)
        def wrapper(*args, **kwargs):

            # Initialize logs for current query

            start_time = time.time()
            start = datetime.now().strftime("%H:%M:%S")

            try:
                result = func(*args, **kwargs)

                end_time = time.time()
                end = datetime.now().strftime("%H:%M:%S")
                duration = (end_time - start_time) * 1000

                # Terminal Log
                logger.info(
                    f"[RAG] {function_name} | "
                    f"Start: {start} | "
                    f"End: {end} | "
                    f"Duration: {duration:.2f} ms | "
                    f"Status: SUCCESS"
                )

                # Store logs for UI
                log_entry = {
                    "function": function_name,
                    "start": start,
                    "end": end,
                    "duration": round(duration, 2),
                    "status": "SUCCESS"
                }

                

                return result

            except Exception as e:

                end_time = time.time()
                end = datetime.now().strftime("%H:%M:%S")
                duration = (end_time - start_time) * 1000

                # Terminal Log
                logger.error(
                    f"[RAG] {function_name} | "
                    f"Start: {start} | "
                    f"End: {end} | "
                    f"Duration: {duration:.2f} ms | "
                    f"Status: ERROR | "
                    f"Error: {str(e)}"
                )

                # Store logs for UI
                log_entry = {
                    "function": function_name,
                    "start": start,
                    "end": end,
                    "duration": round(duration, 2),
                    "status": "ERROR",
                    "error": str(e)
                }

                

                raise e

        return wrapper

    return decorator