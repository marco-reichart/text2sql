"""Contains Python functions."""

import logging
from logging import INFO

logger = logging.getLogger("my_research_project_logger")
logger.setLevel(INFO)


def myfunc(input: int) -> float:
    """Do something."""
    logger.info("myfunc called with input: %s", input)
    return input * 2.0
