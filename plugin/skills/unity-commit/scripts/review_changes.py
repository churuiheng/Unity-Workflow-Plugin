"""Sorts a Unity project's working-tree changes into real changes and noise before a commit.

For every changed file: its status, how much REALLY changed (line endings ignored), what kind of asset it is, and -
for Unity YAML (prefabs, scenes, assets) - which fields changed, so a 5,000-line scene diff reads as "m_LocalPosition
x3, enabled x1". Known noise patterns are flagged with the reason. Read-only: it never stages, restores or commits.

Project-specific noise rules come from <unity project>/.claude/unity-workflow.json:
  "commitNoise": [ { "path": "SFXForge/", "reason": "audio tool data" },
                   { "path": "", "keys": ["dialogueOptionEventID"], "reason": "regenerated ID" } ]
("path" is a substring of the file path; "keys", when given, must be exactly the set of changed fields.)

Usage: python review_changes.py [path-filter ...]     (run from anywhere inside the repo)
"""
import collections
import json
import os
import re
import subprocess
import sys

BIG_FILE_MB = 50          # GitHub refuses files over 100 MB; warn well before
KEY = re.compile(r'^[+-]\s*-?\s*([A-Za-z_][\w .]*?):')
PROPERTY_PATH = re.compile(r'^[ +-]\s*-?\s*propertyPath:\s*(\S+)')
FONT_KEYS = {'m_GlyphTable', 'm_CharacterTable', 'm_UsedGlyphRects', 'm_FreeGlyphRects', 'm_AtlasTextures',
             'image data', '_typelessdata', 'm_CompleteImageSize', 'm_Width', 'm_Height', 'm_X', 'm_Y',
             'm_AtlasWidth', 'm_AtlasHeight', 'm_GlyphIndex', 'm_Unicode', 'm_ElementType', 'm_Metrics',
             'm_GlyphRect', 'm_Scale', 'm_AtlasIndex', 'm_ClassDefinitionType', 'm_HorizontalBearingX',
             'm_HorizontalBearingY', 'm_HorizontalAdvance', 'm_IsDirty', 'm_textureHash', 'm_ImageContentsHash',
             'serializedVersion', 'Hash', 'm_FileID', 'm_PathID', 'm_FontFeatureTable'}

# (test on path, test on the set of changed keys) -> reason. First match wins.
BUILTIN_NOISE = [
    (lambda p: '/Fonts' in p or 'TextMesh Pro' in p or p.endswith('SDF.asset') or 'SDF - Fallback' in p,
     lambda k: k <= FONT_KEYS, 'dynamic TMP font atlas reset by Unity (safe to restore)'),
    (lambda p: 'ProjectSettings/' in p, lambda k: bool(k) and k <= {'serializedVersion', 'adaptiveVsync',
     'adaptiveVsyncExtraA', 'adaptiveVsyncExtraB', 'meshLodThreshold'}, 'Unity version re-serialisation of settings'),
    (lambda p: '/NavMesh' in p and p.endswith('.asset'), lambda k: True, 'NavMesh rebake (expected only if that level changed)'),
    (lambda p: p.endswith('LightingData.asset'), lambda k: True, 'lighting rebake (expected only after a bake)'),
]


def git(*args):
    return subprocess.run(['git', *args], capture_output=True, text=True, encoding='utf-8', errors='replace').stdout


def find_unity_prefix(root):
    """Path of the Unity project inside the repo ('' when the repo root is the project)."""
    for dirpath, dirnames, _ in os.walk(root):
        if 'Assets' in dirnames and 'ProjectSettings' in dirnames:
            rel = os.path.relpath(dirpath, root).replace('\\', '/')
            return '' if rel == '.' else rel + '/'
        dirnames[:] = [d for d in dirnames if not d.startswith('.') and d not in ('Library', 'Temp', 'node_modules')]
        if dirpath.count(os.sep) - root.count(os.sep) >= 2:
            dirnames[:] = []
    return ''


def project_noise(root, prefix):
    try:
        with open(os.path.join(root, prefix, '.claude', 'unity-workflow.json'), encoding='utf-8-sig') as f:
            rules = json.load(f).get('commitNoise', [])
    except (OSError, ValueError):
        return []
    out = []
    for r in rules:
        sub, keys, reason = r.get('path', ''), r.get('keys'), r.get('reason', 'project noise rule')
        out.append((lambda p, s=sub: s in p, (lambda k, ks=set(keys): k == ks) if keys else (lambda k: True), reason))
    return out


def changed_keys(diff):
    """Field names on changed lines. A prefab override stores its field on a `propertyPath:` line and the new value on
    the `value:` line after it, so a changed value is credited to the property it belongs to."""
    keys = collections.Counter()
    last_property = None
    for line in diff.splitlines():
        if line.startswith(('+++', '---', '@@', 'diff ', 'index ')):
            if line.startswith('@@'): last_property = None
            continue
        m = PROPERTY_PATH.match(line)
        if m:
            last_property = m.group(1).split('.Array')[0]
        if line[:1] not in '+-':
            continue
        m = KEY.match(line)
        if not m:
            continue
        key = m.group(1).strip()
        if key in ('value', 'objectReference', 'propertyPath') and last_property:
            key = last_property
        keys[key] += 1
    return keys


def kind(path):
    ext = os.path.splitext(path)[1].lower()
    return {'.cs': 'code', '.prefab': 'prefab', '.unity': 'scene', '.asset': 'asset', '.mat': 'material',
            '.meta': 'meta', '.md': 'doc', '.json': 'data', '.ps1': 'script', '.py': 'script', '.asmdef': 'asmdef',
            '.shader': 'shader', '.shadergraph': 'shader', '.hlsl': 'shader', '.png': 'image', '.fbx': 'model',
            '.anim': 'anim', '.controller': 'anim'}.get(ext, ext or 'file')


def main():
    root = git('rev-parse', '--show-toplevel').strip()
    if not root:
        sys.exit('not inside a git repository')
    os.chdir(root)
    prefix = find_unity_prefix(root)
    noise_rules = BUILTIN_NOISE + project_noise(root, prefix)
    filters = sys.argv[1:]

    git('update-index', '-q', '--refresh')   # clears "modified" flags left by timestamp-only touches
    status = {}
    for line in git('status', '--porcelain', '--untracked-files=all').splitlines():
        code, path = line[:2], line[3:].strip().strip('"')
        if ' -> ' in path: path = path.split(' -> ')[1].strip('"')
        if filters and not any(f.replace('\\', '/') in path for f in filters): continue
        status[path] = code

    if not status:
        print('Working tree clean - nothing to commit.')
        return

    real = {}
    for line in git('diff', 'HEAD', '--numstat', '--ignore-cr-at-eol').splitlines():
        parts = line.split('\t')
        if len(parts) == 3:
            added, removed, path = parts
            real[path] = (added, removed)

    rows, flags = [], []
    for path, code in sorted(status.items()):
        k = kind(path)
        if code == '??':
            size = os.path.getsize(path) / 1e6 if os.path.isfile(path) else 0
            rows.append((path, 'new', '-', k, f'{size:.1f} MB' if size >= 1 else ''))
            if size >= BIG_FILE_MB: flags.append(f'BIG FILE ({size:.0f} MB): {path}')
            continue
        added, removed = real.get(path, ('0', '0'))
        note = ''
        if code.strip() == 'D':
            rows.append((path, 'deleted', f'-{removed}', k, ''))
            continue
        if added == '0' and removed == '0':
            note = 'NO REAL CHANGE (line endings / timestamp only) - leave out'
        elif k in ('prefab', 'scene', 'asset', 'material', 'meta', 'anim') or path.endswith('.asset'):
            keys = changed_keys(git('diff', 'HEAD', '--ignore-cr-at-eol', '-U3', '--', path))
            for test_path, test_keys, reason in noise_rules:
                if test_path(path) and test_keys(set(keys)):
                    note = 'NOISE? ' + reason
                    break
            if not note:
                top = ', '.join(f'{name} x{n}' for name, n in keys.most_common(5))
                note = f'fields: {top}' if top else ''
        if added not in ('-', '0') and os.path.isfile(path) and os.path.getsize(path) / 1e6 >= BIG_FILE_MB:
            flags.append(f'BIG FILE ({os.path.getsize(path) / 1e6:.0f} MB): {path}')
        rows.append((path, 'modified' if code.strip() == 'M' else code.strip(), f'+{added}/-{removed}', k, note))

    staged = [p for p, c in status.items() if c[0] not in (' ', '?')]
    print(f'{len(rows)} changed file(s); {len(staged)} already staged. Unity project: /{prefix or ""}\n')
    width = min(90, max(len(r[0]) for r in rows))
    for path, st, size, k, note in rows:
        shown = path if len(path) <= width else '...' + path[-(width - 3):]
        print(f'{shown:<{width}}  {st:<8} {size:>13}  {k:<8} {note}')

    by_kind = collections.Counter(r[3] for r in rows)
    print('\nBy kind: ' + ', '.join(f'{n} {k}' for k, n in by_kind.most_common()))
    noise = [r[0] for r in rows if r[4].startswith(('NO REAL CHANGE', 'NOISE?'))]
    if noise:
        print(f'\nLikely noise ({len(noise)}): restore with  git checkout -- <path>  (or just leave unstaged) after checking.')
    for f in flags:
        print('\nWARNING ' + f)
    lonely = [p for p in status if not p.endswith('.meta') and status[p] == '??' and os.path.isfile(p)
              and p.startswith(prefix + 'Assets/') and not os.path.isfile(p + '.meta')]
    for p in lonely:
        print(f'\nWARNING new asset without a .meta (Unity has not imported it yet): {p}')


if __name__ == '__main__':
    main()
