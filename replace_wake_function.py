from pathlib import Path
import re

main_path = Path("main.py")
snippet_path = Path("wake_phrase_snippet.py")

original = main_path.read_text(encoding="utf-8")
snippet = snippet_path.read_text(encoding="utf-8").rstrip()

pattern = re.compile(
    r"def wait_for_startup_claps\(.*?\n(?=def _get_api_key)",
    re.DOTALL,
)

match = pattern.search(original)

if not match:
    raise SystemExit("ERROR: Could not find wait_for_startup_claps() block. main.py was NOT changed.")

updated = original[:match.start()] + snippet + "\n\n" + original[match.end():]

main_path.write_text(updated, encoding="utf-8")

print("SUCCESS: Replaced wait_for_startup_claps() with wait_for_wake_phrase().")
print(f"Before: {len(original.encode('utf-8'))} bytes")
print(f"After:  {len(updated.encode('utf-8'))} bytes")
print(f"Before: {len(original.splitlines())} lines")
print(f"After:  {len(updated.splitlines())} lines")