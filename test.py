import openant, pkgutil, sys
import openant.devices

print("OpenANT Version:", getattr(openant, "__version__", "unknown"))
print("\nModule Tree:")
for m in pkgutil.walk_packages(openant.__path__, openant.__name__ + "."):
    print(" -", m.name)