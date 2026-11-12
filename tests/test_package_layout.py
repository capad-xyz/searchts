from pathlib import Path

import searchts


def test_every_package_dir_has_init():
    """Namespace subpackages without __init__.py fail under zipimport."""
    root = Path(searchts.__file__).resolve().parent
    missing = sorted(
        {
            str(py.parent.relative_to(root.parent))
            for py in root.rglob("*.py")
            if "__pycache__" not in py.parts and not (py.parent / "__init__.py").is_file()
        }
    )
    assert missing == [], (
        "every directory under searchts/ that contains .py files needs "
        f"__init__.py so the package imports after a wheel install: {missing}"
    )
