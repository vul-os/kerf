"""Surgically flip kerf.status partial/no -> yes for capabilities the saturation
agents have closed (engine wired + tested + integrated). Operates line-by-line on
frontmatter only, preserving each file's format. The build guard + git are the
safety net: rebuild after running and revert if anything looks wrong.

Usage: python3 scripts/_flip_status.py "Exact Feature Name" "Another Name" ...
Matches a feature row by exact name (case-insensitive) and flips its kerf status.
"""
import re
import sys
import glob

TARGETS = {t.strip().lower() for t in sys.argv[1:]}
if not TARGETS:
    print("no targets given")
    sys.exit(1)

NAME_RE = re.compile(r'^\s*(?:-\s*)?(?:feature|name)\s*:\s*"?([^"\n]+?)"?\s*$')
flipped = 0
files_touched = set()

for path in sorted(glob.glob("public/compare/*.md")):
    lines = open(path, encoding="utf-8").read().split("\n")
    # bound to frontmatter
    if lines[0].strip() != "---":
        continue
    fm_end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    cur_target = False     # is the current feature row one we want to flip?
    side = None            # 'kerf' | 'competitor' | None  (nested-block tracking)
    for i in range(1, fm_end):
        ln = lines[i]
        s = ln.strip()
        m = NAME_RE.match(ln)
        if m and ("feature:" in s or "name:" in s) and not s.startswith(("status", "note", "evidence")):
            cur_target = m.group(1).strip().lower() in TARGETS
            side = None
            continue
        if not cur_target:
            continue
        # inline-flow kerf on one line
        mk = re.match(r'^(\s*kerf:\s*\{)(.*)\}\s*$', ln)
        if mk:
            body = mk.group(2)
            if re.search(r'status:\s*(?!yes)\w', body):
                body = re.sub(r'status:\s*\w+', 'status: yes', body, count=1)
                lines[i] = mk.group(1) + body + "}"
                flipped += 1
                files_touched.add(path)
            continue
        # nested block tracking
        if re.match(r'^\s{4}kerf:\s*$', ln):
            side = 'kerf'
            continue
        if re.match(r'^\s{4}competitor:\s*$', ln):
            side = 'competitor'
            continue
        if side == 'kerf':
            ms = re.match(r'^(\s*status:\s*)"?([^"\n]+?)"?\s*$', ln)
            if ms:
                val = ms.group(2).strip().lower()
                # normalize tokens the build understands
                is_yes = val in ('yes', '[x]', 'shipped') or val.startswith('[x]')
                if not is_yes:
                    lines[i] = ms.group(1) + "yes"
                    flipped += 1
                    files_touched.add(path)
                side = None  # only the first status line in the kerf block
    open(path, "w", encoding="utf-8").write("\n".join(lines))

print(f"flipped {flipped} rows across {len(files_touched)} files")
