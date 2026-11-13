"""
engine/__init__.py
Public API of the TantSaakshi vision engine.
The backend imports from here; do not change these names without agreement.
"""
from engine.compat import grade, fingerprint, match  # noqa: F401 (re-exported)

# Richer interface (backend should migrate to these)
# Imported lazily so the package can be imported even before all modules exist.
def analyze(image_paths, out_dir, debug_dir=None):
    from engine._analyze import analyze as _analyze
    return _analyze(image_paths, out_dir, debug_dir)

def quality_check(image_paths):
    from engine._analyze import quality_check as _qc
    return _qc(image_paths)

def make_fingerprint(image_paths, out_dir):
    from engine._analyze import make_fingerprint as _mfp
    return _mfp(image_paths, out_dir)

