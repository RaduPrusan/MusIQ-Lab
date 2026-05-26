import natten
import natten.functional as f
import pkgutil
import inspect

print("natten path:", natten.__file__)
print("submodules:")
for m in pkgutil.iter_modules(natten.__path__):
    print(" -", m.name)

print()
public = [m for m in dir(f) if not m.startswith("_")]
print("functional public API count:", len(public))
print("any *qk* or *av*:", [m for m in public if "qk" in m.lower() or "av" in m.lower()])

print()
print("na2d signature:", inspect.signature(f.na2d))
print("na1d signature:", inspect.signature(f.na1d))
