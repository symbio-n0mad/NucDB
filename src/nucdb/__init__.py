"""NucDB – Nukliddatenbank mit Lese-API.

Schnellstart::

    from nucdb import NucDB, units
    db = NucDB()
    co = db.nuclide("60Co")
    co.half_life("a"), co.decay_constant("1/h")
    db.find_gammas(1332.5, tol_kev=1.0)
    units.parse_quantity("5,27 a", kind="half_life").value   # Sekunden

Das Format ist in ``docs/NUCDB-SPEC.md`` beschrieben.
"""

from . import names, physics, units
from .db import IncompatibleSchemaError, NucDB, UnknownNuclideError, open_database
from .models import (PRACTICALLY_STABLE_S, ActivationGamma, Chain, DecayMode, Element, Emission, LineMatch, Nuclide,
                     PromptGamma, Source, SpecialLine, Value)
from .names import NuclideId, NuclideNameError
from .overlay import OverlayLockedError
from .schema import SCHEMA_VERSION

__version__ = "1.2.0"

__all__ = [
    "NucDB", "open_database", "IncompatibleSchemaError", "UnknownNuclideError", "OverlayLockedError",
    "Nuclide", "Value", "Source", "Element", "DecayMode", "Emission", "SpecialLine", "PromptGamma",
    "LineMatch", "Chain", "ActivationGamma", "NuclideId", "NuclideNameError", "SCHEMA_VERSION",
    "PRACTICALLY_STABLE_S", "names", "units", "physics",
]
