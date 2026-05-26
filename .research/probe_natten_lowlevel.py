"""Look for split QK/AV ops or RPB support in new NATTEN."""
import natten
import natten.functional as f
import natten.backends as b
import natten.libnatten as ll
import inspect

print("== natten.functional public ==")
for m in sorted(dir(f)):
    if not m.startswith("_"):
        print(" ", m)

print("\n== natten.backends ==")
for m in sorted(dir(b)):
    if not m.startswith("_"):
        print(" ", m)

print("\n== natten.libnatten (low-level) — first 60 ==")
ll_pub = sorted([m for m in dir(ll) if not m.startswith("_")])
print(f"  total: {len(ll_pub)}")
for m in ll_pub[:60]:
    print(" ", m)

print("\n== look for *qk*, *av*, *rpb* across the package ==")
matches = []
for ns_name, ns in [("functional", f), ("backends", b), ("libnatten", ll)]:
    for name in dir(ns):
        n = name.lower()
        if "qk" in n or "av" in n or "rpb" in n or "score" in n:
            matches.append((ns_name, name))
for ns_name, name in matches:
    print(f"  {ns_name}.{name}")

print("\n== na2d does it accept rpb? ==")
sig = inspect.signature(f.na2d)
for p in sig.parameters.values():
    print(f"  {p.name}: {p.annotation if p.annotation is not inspect._empty else ''}")
