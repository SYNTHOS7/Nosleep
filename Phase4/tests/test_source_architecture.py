from backend.services.repository_review import analyze
from test_repository_review import archive


def test_python_import_map_routes_and_containment_are_cited():
    result = analyze(archive({
        'app/main.py': 'from . import worker\n@app.post("/run")\ndef run(value):\n    eval(value)\n',
        'app/worker.py': 'import os\n',
    }))
    graph = result['architecture']
    assert {n['id'] for n in graph['nodes']} == {'app/main.py', 'app/worker.py'}
    assert graph['edges'] == [{'source': 'app/main.py', 'target': 'app/worker.py', 'kind': 'imports', 'evidence': {'file': 'app/main.py', 'line': 1}}]
    assert graph['routes'][0]['line'] == 2
    assert graph['routes'][0]['exposure'] == 'not_verified'
    finding = result['findings'][0]
    assert finding['line'] == 4 and finding['containing_functions'] == ['run']
    assert finding['route_declarations'] == [graph['routes'][0]['id']]
    assert finding['story'][0] == 'Entry point: not established'
    assert graph['unresolved_import_count'] == 1


def test_js_import_resolution_parse_failures_and_no_invented_edges():
    result = analyze(archive({
        'ui/App.jsx': 'import Button from "./Button"\nimport React from "react"\n',
        'ui/Button.jsx': 'export default function Button() {}',
        'bad.py': 'def !',
        'standalone.py': 'x = 3',
    }))
    graph = result['architecture']
    assert len(graph['nodes']) == 4 and len(graph['edges']) == 1
    assert graph['edges'][0]['target'] == 'ui/Button.jsx'
    assert graph['parse_failures'] == ['bad.py']
    assert graph['routes'] == []
    assert 'exploitability' in graph['explanation']


def test_ambiguous_python_source_roots_do_not_create_false_edges():
    result = analyze(archive({'first/util.py': '', 'second/util.py': '', 'main.py': 'import util'}))
    assert result['architecture']['edges'] == []
    assert result['architecture']['unresolved_import_count'] == 1
