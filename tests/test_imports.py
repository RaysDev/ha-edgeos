"""Import every module in the package.

Home Assistant loads a custom component by importing it, so anything that fails
at import time - a name left behind by an edit, a typo in an annotation, a
circular import - takes the whole integration down before a single entity
exists. Nothing else in this suite would necessarily notice, because the other
suites import only the modules they exercise.
"""
import importlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hastub  # noqa: E402

hastub.install()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import custom_components.edgeos as package  # noqa: E402

ok = True
imported = 0

# Walked over the files rather than with `pkgutil`, because the sub-directories
# have no `__init__.py` and are namespace packages, which `walk_packages` does
# not descend into - it would silently check only the eight top level modules.
root = Path(package.__file__).parent

for path in sorted(root.rglob("*.py")):
    relative = path.relative_to(root).with_suffix("")
    parts = [part for part in relative.parts if part != "__init__"]
    name = ".".join([package.__name__, *parts])

    try:
        importlib.import_module(name)
        imported += 1

    except Exception as ex:
        ok = False
        print(f"[FAIL] {name}: {type(ex).__name__}: {ex}")

print(f"[{'PASS' if ok else 'FAIL'}] every module imports: {imported} modules")

# The platforms Home Assistant is asked to set up must all be real modules, or
# the forward at startup fails for a platform that does not exist
from custom_components.edgeos.common.entity_descriptions import PLATFORMS  # noqa: E402

for platform in PLATFORMS:
    name = f"{package.__name__}.{platform}"

    try:
        module = importlib.import_module(name)
        has_setup = hasattr(module, "async_setup_entry")

    except Exception as ex:
        module, has_setup = None, False
        print(f"[FAIL] platform {platform}: {type(ex).__name__}: {ex}")

    if not has_setup:
        ok = False

    print(f"[{'PASS' if has_setup else 'FAIL'}] platform {platform} can be set up")

print()
print("RESULT:", "ALL PASS" if ok else "FAILURES PRESENT")
sys.exit(0 if ok else 1)
