"""Start OpenDroidEmu (ODE).  PyInstaller entry script."""
import sys

from ode.app import main

if __name__ == "__main__":
    sys.exit(main())
