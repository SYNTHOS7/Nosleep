"""Snapshot comparison and conservative reverse-import review guidance."""
from collections import defaultdict, deque
from difflib import SequenceMatcher
import hashlib


def line_fingerprints(files):
    result, remaining = {}, 50000
    for path, text in sorted(files.items()):
        lines = text.splitlines()
        if len(lines) <= min(3000, remaining):
            result[path] = [hashlib.sha256(line.encode()).hexdigest() for line in lines]
            remaining -= len(lines)
    return result


def assess_change_impact(before, after):
    old, new = before.get('source_manifest'), after.get('source_manifest')
    if old is None or new is None:
        return {'available': False, 'reason': 'Rescan both source versions to capture source manifests.'}
    changes = []
    range_budget = 200
    for path in sorted(old.keys() | new.keys()):
        if old.get(path) == new.get(path): continue
        status = 'added' if path not in old else 'removed' if path not in new else 'modified'
        old_lines = before.get('line_fingerprints', {}).get(path)
        new_lines = after.get('line_fingerprints', {}).get(path)
        if status == 'added': old_lines = []
        if status == 'removed': new_lines = []
        spans, omitted = [], False
        available = old_lines is not None and new_lines is not None
        if available:
            for operation, i, j, k, l in SequenceMatcher(None, old_lines, new_lines, autojunk=True).get_opcodes():
                if operation == 'equal': continue
                if range_budget <= 0:
                    omitted = True
                    continue
                spans.append({'operation': operation, 'before': [i + 1, j] if i < j else None,
                              'after': [k + 1, l] if k < l else None})
                range_budget -= 1
        changes.append({'file': path, 'status': status, 'line_ranges_available': available,
                        'ranges_omitted': omitted, 'changed_ranges': spans})
    changed = {item['file'] for item in changes}
    reverse = defaultdict(list)
    # Cite which snapshot supplied the import, including relationships removed by a change.
    seen_edges = set()
    for revision, snapshot in [('after', after), ('before', before)]:
        for edge in snapshot.get('architecture', {}).get('edges', []):
            key = (edge['source'], edge['target'])
            if key in seen_edges: continue
            seen_edges.add(key)
            reverse[edge['target']].append({**edge, 'snapshot': revision})
    queue = deque((path, path, []) for path in sorted(changed))
    visited, impacted = set(changed), []
    while queue:
        node, root, chain = queue.popleft()
        if len(chain) >= 20: continue
        for edge in sorted(reverse[node], key=lambda item: item['source']):
            source = edge['source']
            if source in visited: continue
            visited.add(source)
            path = chain + [edge]
            impacted.append({'file': source, 'changed_dependency': root, 'depth': len(path),
                             'reason': 'Imports a changed file' if len(path) == 1 else 'Transitively imports a changed file',
                             'evidence_chain': path,
                             'action': 'Review callers, input/output contracts and relevant tests. Import reachability does not prove breakage.'})
            queue.append((source, root, path))
    impacted_names = {item['file'] for item in impacted}
    areas = changed | impacted_names
    findings = [{**finding, 'review_reason': 'Changed file' if finding['file'] in changed else 'Potentially affected importing file'}
                for finding in after['findings'] if finding['file'] in areas]
    routes = [route for route in after.get('architecture', {}).get('routes', []) if route['file'] in areas]
    tests = [node['id'] for node in after.get('architecture', {}).get('nodes', [])
             if node['id'] in areas and node['role'] == 'tests']
    mapped = 'architecture' in before and 'architecture' in after
    return {'available': True, 'changed_files': changes, 'potentially_affected': impacted[:200],
            'affected_count': len(impacted), 'affected_list_truncated': len(impacted) > 200,
            'findings_to_review': findings, 'route_candidates_to_retest': routes[:100],
            'route_count': len(routes), 'connected_test_files': tests[:100],
            'dependency_mapping_available': mapped,
            'guidance': ['Inspect changed line ranges in the matching before/after version.',
                         'Review cited import declarations and callers for changed interfaces, types and error handling.',
                         'Rerun relevant tests and verify affected route access controls.',
                         'Finding locations identify review targets; required patch lines need source inspection.'],
            'limitations': 'Static reverse-import impact only, traversed up to 20 imports deep. No bug prediction, taint analysis, runtime call proof or automatic patch. Renames appear as remove/add. Missing or unsupported files may look removed. Line fingerprints are bounded to 3,000 lines/file and 50,000 lines/review; 200 changed ranges are returned. Repeated lines can produce coarse diff ranges.'}
