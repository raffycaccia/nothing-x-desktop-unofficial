"""PyInstaller entry point (relative imports need a package, so `nothingx/__main__.py` cannot be the script)."""
from nothingx.app import main

raise SystemExit(main())
