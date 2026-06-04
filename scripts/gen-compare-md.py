#!/usr/bin/env python3
"""
Regenerate per-vendor compare markdown bodies from public/compare-manifest.json.
Preserves YAML front-matter; overwrites only the markdown body after the second ---.
"""

import json
import re
import os
import sys

COMPARE_DIR = os.path.join(os.path.dirname(__file__), '..', 'public', 'compare')
MANIFEST_PATH = os.path.join(os.path.dirname(__file__), '..', 'public', 'compare-manifest.json')

with open(MANIFEST_PATH) as f:
    manifest = json.load(f)


def extract_kerf(k):
    """Returns (status, note) from kerf field (dict or string)."""
    if isinstance(k, dict):
        status = str(k.get('status', 'yes')).lower()
        note = k.get('note') or k.get('notes') or ''
        return status, str(note)
    elif isinstance(k, str):
        # String form: 'evidence: "..."' means yes with no explicit note
        if k.startswith('evidence'):
            return 'yes', ''
        return 'yes', ''
    return 'yes', ''


def extract_competitor(c):
    """Returns (status, note) from competitor field (dict or string)."""
    if isinstance(c, dict):
        status = str(c.get('status', 'yes')).lower()
        note = c.get('note') or c.get('notes') or ''
        return status, str(note)
    elif isinstance(c, str):
        # 'paid: true/false' -> competitor has feature (free or paid tier)
        if c.startswith('paid:'):
            paid_val = c.split(':', 1)[1].strip().lower()
            if paid_val in ('true', 'yes'):
                return 'paid', ''
            return 'yes', ''
        # '{ status: yes, note: "..." }'
        if '{ status' in c or (c.strip().startswith('{') and 'status' in c):
            m2 = re.search(r'status:\s*(\w+)', c)
            m3 = re.search(r'note:\s*"([^"]*)"', c)
            status = m2.group(1).lower() if m2 else 'yes'
            note = m3.group(1) if m3 else ''
            return status, note
        # 'source: URL' -> feature exists
        if c.startswith('source:'):
            return 'yes', ''
        return 'yes', ''
    return 'yes', ''


def kerf_cell(status):
    if status == 'yes':
        return '✅'
    if status == 'partial':
        return '⚠️ (partial)'
    if status in ('no', 'false'):
        return '🔴 (no)'
    if status == 'true':
        return '✅'
    return '✅'


def comp_cell(status, note):
    if status in ('yes', 'true'):
        return 'Yes'
    if status == 'paid':
        return 'Yes (paid tier)'
    if status == 'partial':
        return 'Partial'
    if status in ('no', 'false'):
        return 'No'
    return status.capitalize()


def get_feat_name(feat):
    return feat.get('name') or feat.get('feature') or ''


def parse_fm_body(content):
    """Split YAML front-matter block from markdown body."""
    if not content.startswith('---'):
        return None, content
    end = content.find('\n---', 4)
    if end < 0:
        return None, content
    # front-matter = everything up to and including the closing ---
    fm = content[:end + 4]
    body = content[end + 4:].lstrip('\n')
    return fm, body


def gap_sentence(no_c, partial_c, comp):
    """Honest one-sentence gap statement."""
    if no_c == 0 and partial_c == 0:
        return f"Kerf covers the full tracked feature set for {comp}; gaps may exist in workflow depth, ecosystem maturity, and community support."
    parts = []
    if partial_c > 0:
        parts.append(f"{partial_c} feature{'s' if partial_c > 1 else ''} partial (engine complete, UI or depth gap)")
    if no_c > 0:
        parts.append(f"{no_c} feature{'s' if no_c > 1 else ''} not yet implemented")
    return "Honest gaps: " + "; ".join(parts) + "."


def generate_body(item):
    slug = item['slug']
    comp = item['competitor']
    tagline = item.get('hero_tagline', '')
    reviewed = item.get('reviewed_at', '2026-06-04')
    features = item.get('features', [])

    # Compute saturation
    yes_c, partial_c, no_c = 0, 0, 0
    for feat in features:
        ks, _ = extract_kerf(feat.get('kerf', ''))
        if ks == 'yes':
            yes_c += 1
        elif ks == 'partial':
            partial_c += 1
        else:
            no_c += 1
    total = yes_c + partial_c + no_c
    pct = round(100 * (yes_c + 0.5 * partial_c) / total) if total else 0

    lines = []

    # Title
    lines.append(f"# Kerf vs {comp}")
    lines.append('')
    lines.append(tagline)
    lines.append('')
    lines.append(f"*Last reviewed: {reviewed}*")
    lines.append('')

    # Summary section
    lines.append('## Summary')
    lines.append('')
    gap = gap_sentence(no_c, partial_c, comp)
    lines.append(
        f"Kerf saturates **{pct}%** of {comp}'s feature surface "
        f"({yes_c} yes, {partial_c} partial, {no_c} no out of {total} features tracked here). "
        f"{gap}"
    )
    lines.append('')

    # Feature comparison table
    if features:
        lines.append('## Feature comparison')
        lines.append('')
        lines.append(f"| Feature | Kerf | {comp} | Notes |")
        lines.append("|---------|------|" + "-" * (len(comp) + 2) + "|-------|")

        for feat in features:
            name = get_feat_name(feat)
            if not name:
                continue
            ks, kn = extract_kerf(feat.get('kerf', ''))
            cs, cn = extract_competitor(feat.get('competitor', ''))
            kerf_col = kerf_cell(ks)
            comp_col = comp_cell(cs, cn)
            # Notes: prefer kerf note if present, else competitor note
            note = kn or cn or ''
            # Sanitize note for markdown table (no newlines, escape pipes)
            note = note.replace('\n', ' ').replace('|', '\\|')
            # Truncate long notes
            if len(note) > 120:
                note = note[:117] + '...'
            lines.append(f"| {name} | {kerf_col} | {comp_col} | {note} |")

        lines.append('')

    # What Kerf does that competitor doesn't
    kerf_only = []
    for feat in features:
        name = get_feat_name(feat)
        if not name:
            continue
        ks, kn = extract_kerf(feat.get('kerf', ''))
        cs, cn = extract_competitor(feat.get('competitor', ''))
        if ks == 'yes' and cs in ('no', 'false', 'paid'):
            kerf_only.append((name, kn or cn))

    if kerf_only:
        lines.append(f"## What Kerf does that {comp} doesn't")
        lines.append('')
        for name, note in kerf_only[:12]:  # cap at 12 bullets
            note_str = f" — {note}" if note else ''
            lines.append(f"- **{name}**{note_str}")
        if len(kerf_only) > 12:
            lines.append(f"- *(and {len(kerf_only) - 12} more features not covered by {comp})*")
        lines.append('')

    # What's honestly outstanding
    outstanding = []
    for feat in features:
        name = get_feat_name(feat)
        if not name:
            continue
        ks, kn = extract_kerf(feat.get('kerf', ''))
        if ks in ('partial', 'no'):
            outstanding.append((name, ks, kn))

    if outstanding:
        lines.append("## What's honestly outstanding")
        lines.append('')
        for name, ks, note in outstanding:
            status_label = 'Partial' if ks == 'partial' else 'Not yet implemented'
            note_str = f": {note}" if note else ''
            lines.append(f"- **{name}** ({status_label}){note_str}")
        lines.append('')

    # Pricing
    category = item.get('category', '')
    is_paid_competitor = False
    for feat in features:
        cs, _ = extract_competitor(feat.get('competitor', ''))
        if cs == 'paid':
            is_paid_competitor = True
            break

    lines.append('## Pricing')
    lines.append('')
    if is_paid_competitor:
        lines.append(
            f"{comp} is a commercial product; pricing varies by tier, seat count, and region. "
            "Kerf is MIT open-core: the full feature set is free to run locally (single Go binary, "
            "Postgres required). A hosted option with pay-as-you-go billing is available for teams "
            "that don't want to self-host. No feature gates — the MIT licence means you can inspect, "
            "fork, and self-host the entire codebase."
        )
    else:
        lines.append(
            f"{comp} is free and open-source. "
            "Kerf is also MIT open-core: free to run locally (single Go binary, Postgres required). "
            "A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. "
            "No feature gates — MIT licensed throughout."
        )
    lines.append('')

    return '\n'.join(lines)


# Collect manifest slugs
manifest_slugs = {item['slug']: item for item in manifest['items']}

count = 0
for slug, item in manifest_slugs.items():
    md_path = os.path.join(COMPARE_DIR, f"{slug}.md")
    if not os.path.exists(md_path):
        print(f"  SKIP (file not found): {slug}.md")
        continue

    with open(md_path, encoding='utf-8') as f:
        content = f.read()

    fm, old_body = parse_fm_body(content)
    if fm is None:
        print(f"  SKIP (no front-matter): {slug}.md")
        continue

    new_body = generate_body(item)
    new_content = fm + '\n\n' + new_body

    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(new_content)

    # Compute saturation for report
    yes_c, partial_c, no_c = 0, 0, 0
    for feat in item.get('features', []):
        ks, _ = extract_kerf(feat.get('kerf', ''))
        if ks == 'yes': yes_c += 1
        elif ks == 'partial': partial_c += 1
        else: no_c += 1
    total = yes_c + partial_c + no_c
    pct = round(100 * (yes_c + 0.5 * partial_c) / total) if total else 0
    print(f"  {slug:20s} {pct:3d}% ({total:3d} features)")
    count += 1

print(f"\nDone: {count} files regenerated.")
