import io
import zipfile
import pytest
from fastapi.testclient import TestClient
from backend.services import repository_review as review
from backend.storage.local_store import LocalStore


def archive(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as z:
        for path, text in files.items(): z.writestr('repo/' + path, text)
    return output.getvalue()


def test_rules_locations_comparison_and_persistence(tmp_path, monkeypatch):
    source = 'import subprocess as sp\nimport pickle\nfrom requests import get\nsp.run(command, shell=True)\npickle.loads(data)\nget(url, verify=False)\neval(value)\n'
    first = review.analyze(archive({'app.py': source, 'ui.jsx': '<div dangerouslySetInnerHTML={data} />'}))
    assert len(first['findings']) == 5
    assert next(f for f in first['findings'] if f['rule'] == 'shell-command')['line'] == 4
    assert all(f['story'][0] == 'Entry point: not established' for f in first['findings'])
    assert source not in str(first)
    second = review.analyze(archive({'app.py': '# reviewed\n' + source, 'ui.jsx': '<div>{data}</div>'}))
    comparison = review.compare(first, second)
    assert len(comparison['still_present']) == 4 and len(comparison['no_longer_observed']) == 1
    store = LocalStore(tmp_path / 'review.sqlite')
    monkeypatch.setattr(review, 'repository', lambda: store)
    review.save('one', first)
    assert review.list_reviews('two') == []
    assert LocalStore(store.path).list_repository_reviews('one')[0] == first


@pytest.mark.parametrize('path', ['../escape.py', '/escape.py', 'a\\b.py', 'C:/x.py'])
def test_archive_paths_rejected(path):
    out = io.BytesIO()
    # Windows ZipInfo normalizes backslashes at construction. Preserve the raw
    # adversarial name to exercise archives produced on other operating systems.
    entry = zipfile.ZipInfo('placeholder.py')
    entry.filename = path
    with zipfile.ZipFile(out, 'w') as z: z.writestr(entry, 'eval(x)')
    with pytest.raises(ValueError): review.analyze(out.getvalue())


def test_parse_failure_and_no_matches_are_not_safe_verdicts():
    result = review.analyze(archive({'bad.py': 'def !', 'okay.py': '# eval(x)\nx = "exec(y)"'}))
    assert result['parse_errors'] == ['bad.py'] and result['findings'] == []
    assert 'not a full security audit' in result['limitations'][0]


@pytest.mark.parametrize('url', ['http://github.com/a/b', 'https://localhost/a/b', 'https://github.com/a/b/tree/main', 'https://github.com/../b', 'https://github.com@evil.test/a/b'])
def test_github_url_rejected_before_network(url):
    with pytest.raises(ValueError): review.github_snapshot(url)


def test_api_roles_and_workspace_scope(monkeypatch, tmp_path):
    import backend.security.access as access
    from backend.app import app
    monkeypatch.setenv('AUTH_MODE', 'neon')
    monkeypatch.setattr(access, 'authenticate', lambda _: access.Principal('user', '', {'a': 'editor', 'b': 'viewer'}))
    monkeypatch.setattr(review, 'repository', lambda: LocalStore(tmp_path / 'api.sqlite'))
    with TestClient(app) as client:
        response = client.post('/v1/workspaces/a/repository-reviews', files={'file': ('source.zip', archive({'main.py': 'eval(value)'}), 'application/zip')})
        assert response.status_code == 200, response.text
        identifier = response.json()['id']
        assert client.get('/v1/workspaces/a/repository-reviews').json()['reviews'][0]['id'] == identifier
        assert client.get('/v1/workspaces/b/repository-reviews').json()['reviews'] == []
        assert client.post('/v1/workspaces/b/repository-reviews', data={'github_url': 'x'}).status_code == 403
        assert client.get(f'/v1/workspaces/b/repository-comparison?before={identifier}&after={identifier}').status_code == 404
        assert client.get('/v1/workspaces/other/repository-reviews').status_code == 403
