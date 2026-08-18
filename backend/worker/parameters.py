"""Worker composition assemble, Beat in-code constants, and derived reaper interval."""

from __future__ import annotations

import logging
import os

from backend.admin.parameters import ADMIN_PARAMETER_SPECS
from backend.admin.system_parameters import list_registered_specs, occupy_registered_parameters, register_parameters
from backend.jobs.parameters import JOBS_PARAMETER_SPECS

__all__ = [
    "BEAT_MAX_INTERVAL_SEC",
    "BEAT_SYNC_EVERY_SEC",
    "assemble_system_parameters",
]

logger = logging.getLogger(__name__)

# In-code constants. Changing them is a release (docs/business-system-parameters.md §5.2).
BEAT_SYNC_EVERY_SEC = 30
BEAT_MAX_INTERVAL_SEC = 5

_GROUP_ORDER = ("session", "jobs")


def assemble_system_parameters() -> None:
    """Composition: collect published spec lists, freeze the registry, occupy seeds."""
    register_parameters(
        (
            *ADMIN_PARAMETER_SPECS,
            *JOBS_PARAMETER_SPECS,
        ),
        group_order=_GROUP_ORDER,
    )
    occupy_registered_parameters()
    _warn_leftover_env_names()


def _warn_leftover_env_names() -> None:
    for spec in list_registered_specs():
        for name in (spec.key.upper(), f"REFRAQ_{spec.key.upper()}"):
            if name in os.environ:
                logger.warning(
                    "environment variable %s is ignored; %s is a System Parameter "
                    "tuned in Platform Settings",
                    name,
                    spec.key,
                )
