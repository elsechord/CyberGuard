#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/dist/skills"
rm -rf "$OUT"
mkdir -p "$OUT"

for skill in "$ROOT"/skills/*; do
  [[ -d "$skill" ]] || continue
  [[ -f "$skill/SKILL.md" ]] || { echo "Missing SKILL.md in $skill" >&2; exit 1; }
  name="$(basename "$skill")"
  python3 - "$skill" "$OUT/$name.zip" <<'PY'
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

source = Path(sys.argv[1])
target = Path(sys.argv[2])
with ZipFile(target, "w", ZIP_DEFLATED) as archive:
    for path in sorted(source.rglob("*")):
        if path.is_file():
            archive.write(path, path.relative_to(source))
PY
done

sha256sum "$OUT"/*.zip > "$OUT/SHA256SUMS"
echo "Packaged Skills in $OUT"

