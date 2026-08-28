"""Resolve data files shipped inside the package (the default tool suite and
the built-in offline fixtures).

Before this module existed, ``tooldrift`` reached for the default suite and the
built-in fixtures via CWD-relative paths (``examples/suite.weather.yaml``,
``tests/fixtures/<provider>_tool_calls.json``). Those paths only resolve when
the process runs from a checkout of the repo, and the wheel ships neither
``examples/`` nor ``tests/`` — so an installed user running the documented
zero-key demo ``tooldrift snapshot --provider deepseek --from-fixtures`` from
any other directory hit a "could not load suite" error before ever seeing a
red/green result.

The suite and the two built-in fixtures are now shipped as package data under
``tooldrift/_data/`` (runtime copies; the repo's ``examples/`` and
``tests/fixtures/`` stay as the browsing/test copies). This module locates them
relative to the package on disk, so resolution is independent of the process
CWD for both an editable checkout and an installed (unzipped) wheel.
"""

from __future__ import annotations

from pathlib import Path

# The package directory (the parent of this file). For an editable install this
# is the source tree; for an installed wheel it is site-packages/tooldrift.
# Either way _data ships alongside the code as package data, so resolution is
# independent of the process CWD.
_DATA_DIR = Path(__file__).resolve().parent / "_data"


def default_suite_path() -> Path:
    """The bundled default tool suite used when ``--suite`` is omitted."""
    return _DATA_DIR / "suite.weather.yaml"


def builtin_fixture_path(filename: str) -> Path:
    """The bundled offline fixture file (e.g. ``deepseek_tool_calls.json``)."""
    return _DATA_DIR / "fixtures" / filename
