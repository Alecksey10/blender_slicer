"""Versions of the data contract.

Four versions are independent (see ``docs/architecture/01_architecture.md``):

* ``PROTOCOL_VERSION`` — shape of request/result, shared by adapters and engine;
* ``SCHEMA_VERSION`` — current JSON schema written by the codec;
* ``SUPPORTED_SCHEMA_VERSIONS`` — schemas the engine still accepts;
* ``ENGINE_VERSION`` — behaviour of the algorithms.
"""

from __future__ import annotations

PROTOCOL_VERSION = "1.1"
SCHEMA_VERSION = "1.1"
SUPPORTED_SCHEMA_VERSIONS = ("1.0", "1.1")
MIN_SCHEMA_VERSION = "1.0"

ENGINE_NAME = "slicer-engine"
ENGINE_VERSION = "0.3.1"

UNITS = "mm"
