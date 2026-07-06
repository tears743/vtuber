import json, sys
sys.stdout.reconfigure(encoding='utf-8')

m = json.load(open(r'D:\workspace\videoFactory\data\2026-07-05\media\manifest.json', 'r', encoding='utf-8'))

# Videos
vids = [(k, v) for k, v in m.items() if v.get('video')]
print(f"Videos: {len(vids)}")
for k, v in vids:
    vi = v["video"]
    dur = vi.get("duration_s")
    summary = vi.get("summary", "")
    has_summary = bool(summary)
    print(f"  {k[:50]}: duration={dur}, has_summary={has_summary} ({len(summary)} chars)")

print()

# READMEs
readmes = [(k, v) for k, v in m.items() if v.get('readme')]
print(f"READMEs: {len(readmes)}")
for k, v in readmes:
    ri = v["readme"]
    has_summary = bool(ri.get("summary"))
    print(f"  {k[:50]}: has_summary={has_summary}")
