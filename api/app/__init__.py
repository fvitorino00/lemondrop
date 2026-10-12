"""lemondrop API application package.

Marks `app` as a package so that `app.main:app` is importable as a module path.
uvicorn imports it by that dotted path, which is why the CMD in the Dockerfile
pairs with this directory rather than importing a bare `main`.
"""
