"""Worker composition assemble, Beat in-code constants, and derived reaper interval."""

from __future__ import annotations

import logging
import os

from backend.admin.parameters import ADMIN_PARAMETER_SPECS
from backend.admin.system_parameters import (
    StringEnumConstraint,
    ParameterSpec,
    list_registered_specs,
    occupy_registered_parameters,
    register_parameters,
)
from backend.core.time_zones import iana_zone_ids
from backend.jobs.parameters import JOBS_PARAMETER_SPECS
from backend.metadata.parameters import METADATA_PARAMETER_SPECS

__all__ = [
    "BEAT_MAX_INTERVAL_SEC",
    "BEAT_SYNC_EVERY_SEC",
    "WORKER_PARAMETER_SPECS",
    "assemble_system_parameters",
]

logger = logging.getLogger(__name__)

# In-code constants. Changing them is a release (docs/business-system-parameters.md §5.2).
BEAT_SYNC_EVERY_SEC = 30
BEAT_MAX_INTERVAL_SEC = 5

_GROUP_ORDER = ("session", "jobs", "schedules", "query")


def _realign_schedule_timezone() -> None:
    """Apply the stored zone to enabled cron commitments. Import is local to avoid a cycle."""
    from backend.worker.api import realign_cron_commitments

    realign_cron_commitments()


WORKER_PARAMETER_SPECS: tuple[ParameterSpec, ...] = (
    ParameterSpec(
        key="schedule_timezone",
        constraint=StringEnumConstraint(values=iana_zone_ids()),
        seed="UTC",
        owner="worker",
        group="schedules",
        operator_action_required=False,
        apply_note_key="settings.parameter.schedule_timezone.apply",
        label_key="settings.parameter.schedule_timezone.label",
        help_key="settings.parameter.schedule_timezone.help",
        on_written=_realign_schedule_timezone,
    ),
)


def assemble_system_parameters() -> None:
    """Composition: collect published spec lists, freeze the registry, occupy seeds."""
    register_parameters(
        (
            *ADMIN_PARAMETER_SPECS,
            *JOBS_PARAMETER_SPECS,
            *WORKER_PARAMETER_SPECS,
            *METADATA_PARAMETER_SPECS,
        ),
        group_order=_GROUP_ORDER,
    )
    occupy_registered_parameters()
    _warn_leftover_env_names()
    _warn_dead_env()


_DEAD_ENV: tuple[tuple[str, str], ...] = (
    (
        "REFRAQ_EMBEDDING_API_URL",
        "Catalog Search hybrid is an in-use Model Service",
    ),
    (
        "REFRAQ_EMBEDDING_MODEL",
        "Catalog Search hybrid is an in-use Model Service",
    ),
    (
        "REFRAQ_EMBEDDING_TIMEOUT_SEC",
        "Catalog Search hybrid is an in-use Model Service",
    ),
    (
        "REFRAQ_CATALOG_FAIL_SAFE_THRESHOLD",
        "catalog fail-safe is retired; a complete successful collect always commits",
    ),
    (
        "REFRAQ_PEEK_SLOTS",
        "use REFRAQ_ADMISSION_SLOTS (ADR 0045)",
    ),
)


def _warn_dead_env() -> None:
    for name, reason in _DEAD_ENV:
        if name in os.environ:
            logger.warning("environment variable %s is ignored; %s", name, reason)


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
