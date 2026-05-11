"""Configuracao compartilhada do pytest."""

from __future__ import annotations

import sys
from pathlib import Path

# Permite `import etl.lib.*` quando pytest e invocado da raiz.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
