"""Binary wheel support based on Flit."""

import logging
import os
import pathlib
import tempfile
import typing

from flit_core.buildapi import (
    build_sdist,
    get_requires_for_build_sdist,
    get_requires_for_build_wheel,
    prepare_metadata_for_build_wheel,
)

from ._version import __version__
from ._wheels import WheelBuilder

__all__ = [
    "__version__",
    "build_sdist",
    "build_wheel",
    "get_requires_for_build_sdist",
    "get_requires_for_build_wheel",
    "prepare_metadata_for_build_wheel",
]


logger = logging.getLogger(__name__)


def build_wheel(
    wheel_directory: str,
    config_settings: typing.Optional[dict] = None,
    metadata_directory: typing.Optional[str] = None,
) -> str:
    """Builds a wheel, places it in wheel_directory.

    Basically copied from Flit's implementation.
    """
    conf = pathlib.Path("pyproject.toml")
    logger.info("Built wheel: %s", wheel_directory)
    fd, temp = tempfile.mkstemp(suffix=".whl", dir=wheel_directory)
    try:
        with open(fd, "wb") as f:
            wb = WheelBuilder.from_pyproject_toml(conf, f)
            wb.build()
        wheel_path = pathlib.Path(wheel_directory, wb.wheel_filename)
        os.replace(temp, wheel_path)
    except Exception:
        os.unlink(temp)
        raise

    return wheel_path.name
