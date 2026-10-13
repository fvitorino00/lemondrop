"""Make the `app` package importable from the test suite.

There is no `pyproject.toml`, no `setup.py` and no installed package here — the
application is run by uvicorn as `app.main:app` from inside the image, with the
image's `WORKDIR /app` as the import root. Locally there is no equivalent, so
`api/` is put on `sys.path` here, once, before any test module is imported.

This is the same mechanism alembic.ini uses (`prepend_sys_path = .`), for the
same reason: one source root, no packaging ceremony, no second copy of the
dependency graph that could drift from what the image actually installs.

It lives in `conftest.py` rather than at the top of `test_db.py` because
conftest.py is imported by pytest before collecting any test module, so the path
is in place regardless of which order the files are collected in or whether a
future test module also wants to import application code.
"""

import sys
from pathlib import Path

# The `api/` directory — the directory that CONTAINS the `app` package, which is
# what has to be on the path. Adding `api/app` instead would make `app.config`
# unimportable, which is the mistake this line exists to prevent.
API_DIR = Path(__file__).resolve().parent.parent

if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))