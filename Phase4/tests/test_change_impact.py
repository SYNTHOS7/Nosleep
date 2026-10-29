from backend.services.repository_review import analyze, compare
from test_repository_review import archive


def scan(files): return analyze(archive(files))


def test_changed_lines_reverse_imports_and_review_locations():
    common = {'routes.py': 'import service\n@app.post("/run")\ndef run(x):\n    return service.work(x)\n',
              'tests/test_routes.py': 'import routes\n', 'unrelated.py': 'x=1\n'}
    before = scan({**common, 'service.py': 'def work(x):\n    return x\n'})
    after = scan({**common, 'service.py': 'def work(x):\n    return eval(x)\n'})
    impact = compare(before, after)['change_impact']
    assert impact['changed_files'] == [{'file':'service.py','status':'modified','line_ranges_available':True,'ranges_omitted':False,'changed_ranges':[{'operation':'replace','before':[2,2],'after':[2,2]}]}]
    affected = {item['file']: item for item in impact['potentially_affected']}
    assert set(affected) == {'routes.py', 'tests/test_routes.py'}
    assert affected['routes.py']['evidence_chain'][0]['evidence']['line'] == 1
    assert affected['tests/test_routes.py']['depth'] == 2
    assert impact['findings_to_review'][0]['line'] == 2
    assert impact['route_candidates_to_retest'][0]['file'] == 'routes.py'
    assert impact['connected_test_files'] == ['tests/test_routes.py']


def test_removed_imports_old_snapshots_add_delete_and_cycles():
    before = scan({'a.py':'import b\n','b.py':'import a\n','old.py':'x=1\n'})
    after = scan({'a.py':'import b\n','b.py':'x=2\n','new.py':'x=3\n'})
    impact = compare(before, after)['change_impact']
    assert {f['status'] for f in impact['changed_files']} == {'added','removed','modified'}
    assert impact['affected_count'] == 1
    assert impact['potentially_affected'][0]['file'] == 'a.py'
    assert compare(after, after)['change_impact']['changed_files'] == []


def test_legacy_scans_do_not_invent_line_ranges():
    before, after = scan({'a.py':'x=1'}), scan({'a.py':'x=2'})
    del before['line_fingerprints']
    impact = compare(before, after)['change_impact']
    assert not impact['changed_files'][0]['line_ranges_available']
    assert impact['changed_files'][0]['changed_ranges'] == []
    del before['source_manifest']
    assert not compare(before, after)['change_impact']['available']
