"""python -m tak.pipeline {setup,build,check,validate}: the avatar pipeline without the Studio."""
import sys

from .cli import main

sys.exit(main())
