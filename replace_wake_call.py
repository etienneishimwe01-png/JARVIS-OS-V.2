from pathlib import Path

path = Path("main.py")
text = path.read_text(encoding="utf-8")

old = "    if not wait_for_startup_claps():\n        return"
new = "    if not wait_for_wake_phrase():\n        return"

count = text.count(old)

if count != 1:
    raise SystemExit(
        f"ERROR: Expected exactly 1 old startup call, found {count}. main.py was NOT changed."
    )

updated = text.replace(old, new)

path.write_text(updated, encoding="utf-8")

print("SUCCESS: Startup call changed to wait_for_wake_phrase().")
print(f"Before: {len(text.encode('utf-8'))} bytes")
print(f"After:  {len(updated.encode('utf-8'))} bytes")
print(f"Before: {len(text.splitlines())} lines")
print(f"After:  {len(updated.splitlines())} lines")