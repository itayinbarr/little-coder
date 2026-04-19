"""
Backward-compatibility shim.
Real implementation: modular/voice/

'from voice import X' and 'from voice.stt import Y' still work.
"""
import importlib as _il
import sys as _sys

# Import the real package — triggers its own __init__
_real = _il.import_module("modular.voice")

# Re-export everything from the real package
from modular.voice import *  # noqa: F401, F403

# Register submodules so 'from voice.X import Y' works
for _sub in ["recorder", "stt", "keyterms", "cmd"]:
    try:
        _m = _il.import_module(f"modular.voice.{_sub}")
        _sys.modules.setdefault(f"voice.{_sub}", _m)
    except ImportError:
        pass
