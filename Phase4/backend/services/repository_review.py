"""Bounded passive source review. Findings are candidates, never exploit proofs."""
import ast
import hashlib
import io
import json
import re
import stat
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import PurePosixPath

import requests
from backend.services.asset_service import repository

MAX_ARCHIVE = 10 * 1024 * 1024
MAX_SOURCE = 20 * 1024 * 1024
RULESET = "source-review-v1"
_memory, _lock = {}, threading.RLock()


def github_snapshot(url):
    match = re.fullmatch(r"https://github\.com/([A-Za-z0-9_.-]{1,100})/([A-Za-z0-9_.-]{1,100})/?", url)
    if not match or any(part in {'.', '..'} for part in match.groups()):
        raise ValueError("Use a public https://github.com/owner/repository URL")
    owner, name = match.groups()
    name = name.removesuffix('.git')
    session = requests.Session()
    session.trust_env = False
    deadline = time.monotonic() + 60
    def read(url, maximum):
        with session.get(url, timeout=(10, 15), stream=True, allow_redirects=False,
                         headers={'Accept': 'application/vnd.github+json'}) as response:
            if response.status_code in {403, 429} and (response.headers.get('X-RateLimit-Remaining') == '0' or response.status_code == 429):
                raise ValueError("GitHub's public API rate limit has been reached. Try later or upload a repository ZIP.")
            if response.status_code != 200:
                raise ValueError("GitHub could not provide this public repository. Check the URL or upload a ZIP.")
            result = bytearray()
            for chunk in response.iter_content(65536):
                result.extend(chunk)
                if len(result) > maximum or time.monotonic() > deadline:
                    raise ValueError("Repository download exceeds the size or time limit; upload a smaller ZIP")
            return bytes(result)
    try:
        metadata = json.loads(read(f'https://api.github.com/repos/{owner}/{name}/commits?per_page=1', 1000000))
        commit = metadata[0]['sha']
        if not re.fullmatch('[0-9a-f]{40}', commit):
            raise ValueError("Invalid GitHub commit identity")
        data = read(f'https://codeload.github.com/{owner}/{name}/zip/{commit}', MAX_ARCHIVE)
        return data, f'https://github.com/{owner}/{name}', commit
    except (requests.RequestException, KeyError, IndexError, TypeError, json.JSONDecodeError):
        raise ValueError("GitHub download failed. Try again or upload a repository ZIP.") from None
    finally:
        session.close()


def inspect_archive(data):
    if len(data) > MAX_ARCHIVE:
        raise ValueError("ZIP exceeds 10 MiB")
    files, skipped = {}, []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > 5000 or sum(item.file_size for item in entries) > MAX_SOURCE:
                raise ValueError("Repository exceeds 5,000 entries or 20 MiB expanded")
            roots = {item.filename.split('/')[0] for item in entries}
            strip_root = len(roots) == 1 and all('/' in item.filename for item in entries)
            for item in entries:
                raw_name = item.orig_filename
                path = PurePosixPath(raw_name)
                if path.is_absolute() or '..' in path.parts or chr(92) in raw_name or ':' in raw_name or any(ord(c) < 32 for c in raw_name):
                    raise ValueError("Unsafe archive path")
                if stat.S_ISLNK(item.external_attr >> 16) or item.flag_bits & 1:
                    raise ValueError("Symlinks and encrypted entries are unsupported")
                if item.is_dir():
                    continue
                name = '/'.join(path.parts[1:] if strip_root else path.parts)
                if name in files:
                    raise ValueError("Duplicate source path")
                if any(part in {'.git', 'node_modules', '.venv', 'venv', 'dist', 'build', '__pycache__'} for part in path.parts) or path.suffix not in {'.py', '.js', '.jsx', '.ts', '.tsx'} or item.file_size > 300000:
                    skipped.append(name)
                    continue
                try:
                    files[name] = archive.read(item).decode('utf-8')
                except UnicodeDecodeError:
                    skipped.append(name)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError):
        raise ValueError("Invalid or unsupported ZIP archive") from None
    if not files:
        raise ValueError("No supported UTF-8 Python or JavaScript/TypeScript source files found")
    return files, skipped


def analyze(data, origin='uploaded ZIP', commit=None):
    files, skipped = inspect_archive(data)
    findings, entries, parse_errors = [], [], []
    def add(path, line, rule, title, fix, operation):
        # Never store raw code: a source line may contain credentials or personal data.
        if len(findings) >= 1000:
            raise ValueError('More than 1,000 finding candidates; review a smaller source archive')
        evidence = files[path].splitlines()[line - 1]
        identity = hashlib.sha256(f'{path}:{rule}:{evidence.strip()}'.encode()).hexdigest()
        findings.append({'id': identity, 'rule': rule, 'file': path, 'line': line,
                         'source_line_sha256': hashlib.sha256(evidence.encode()).hexdigest(),
                         'title': title, 'status': 'needs_review', 'operation': operation,
                         'fix': fix, 'unknowns': ['Attacker control of input', 'Runtime reachability and effective controls'],
                         'story': ['Entry point: not established', operation, 'Impact: requires verification']})
    for path, source in sorted(files.items()):
        if path.endswith('.py'):
            try:
                tree = ast.parse(source)
            except (SyntaxError, RecursionError):
                parse_errors.append(path)
                continue
            if sum(1 for _ in ast.walk(tree)) > 50000:
                parse_errors.append(path)
                continue
            aliases = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names: aliases[alias.asname or alias.name] = alias.name
                elif isinstance(node, ast.ImportFrom) and node.module:
                    for alias in node.names: aliases[alias.asname or alias.name] = node.module + '.' + alias.name
            def called(node):
                if isinstance(node, ast.Name): return aliases.get(node.id, node.id)
                if isinstance(node, ast.Attribute): return called(node.value) + '.' + node.attr
                return ''
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call): continue
                name = called(node.func)
                if name.rsplit('.', 1)[-1] in {'get', 'post', 'put', 'delete', 'patch', 'route'} and isinstance(node.func, ast.Attribute) and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str) and node.args[0].value.startswith('/'):
                    entries.append({'file': path, 'line': node.lineno, 'kind': 'route declaration candidate'})
                if name in {'eval', 'exec', 'builtins.eval', 'builtins.exec'}:
                    add(path, node.lineno, 'dynamic-code', 'Dynamic code execution requires review', 'Replace dynamic execution with explicit allowed operations; establish whether input is untrusted.', 'Dynamic code execution')
                if name.startswith('subprocess.') and any(k.arg == 'shell' and isinstance(k.value, ast.Constant) and k.value.value is True for k in node.keywords):
                    add(path, node.lineno, 'shell-command', 'Shell-enabled process requires review', 'Prefer an argument list with shell=False; validate command inputs.', 'Shell command execution')
                if name in {'pickle.load', 'pickle.loads'}:
                    add(path, node.lineno, 'pickle-input', 'Pickle deserialization requires trusted input', 'Use a data-only format for untrusted inputs and validate its schema.', 'Object deserialization')
                if name.startswith(('requests.', 'httpx.')) and any(k.arg == 'verify' and isinstance(k.value, ast.Constant) and k.value.value is False for k in node.keywords):
                    add(path, node.lineno, 'tls-disabled', 'TLS certificate verification disabled', 'Enable certificate verification and configure a trusted CA when needed.', 'Unverified TLS connection')
        else:
            # Deliberately narrow line candidates, not a JavaScript parser or taint analysis.
            for line, text in enumerate(source.splitlines(), 1):
                if re.search(r'\bdangerouslySetInnerHTML\s*=', text):
                    add(path, line, 'raw-html', 'Raw HTML rendering requires review', 'Render text normally or sanitize HTML with a maintained sanitizer; trace the input source.', 'Raw HTML rendering')
    findings = list({item['id']: item for item in findings}.values())
    return {'id': uuid.uuid4().hex, 'created_at': datetime.now(timezone.utc).isoformat(),
            'origin': origin, 'commit': commit, 'archive_sha256': hashlib.sha256(data).hexdigest(),
            'ruleset': RULESET, 'files_analyzed': len(files), 'files_skipped': len(skipped),
            'source_manifest': {path: hashlib.sha256(text.encode()).hexdigest() for path, text in sorted(files.items())},
            'parse_errors': parse_errors, 'entry_candidates': entries[:500], 'findings': findings,
            'limitations': ['Five narrow source rules only; not a full security audit.',
                           'No dependency, secret, taint, cross-file call graph or runtime analysis.',
                           'Routes are candidates; no connection to findings or exploit path is inferred.',
                           'Code is never executed. Raw source is not retained; line hashes identify evidence.',
                           'Disappeared findings are not proof of remediation.']}


def save(workspace, result):
    store = repository()
    if hasattr(store, 'save_repository_review'):
        store.save_repository_review(workspace, result)
    else:
        with _lock: _memory[workspace, result['id']] = json.loads(json.dumps(result))
    return result


def list_reviews(workspace):
    store = repository()
    if hasattr(store, 'list_repository_reviews'): return store.list_repository_reviews(workspace)
    with _lock: return sorted([json.loads(json.dumps(v)) for (ws, _), v in _memory.items() if ws == workspace], key=lambda x:x['created_at'], reverse=True)[:20]


def compare(before, after):
    if before['origin'] != after['origin'] or before['ruleset'] != after['ruleset']:
        raise ValueError('Compare the same repository origin and ruleset')
    old, new = {f['id'] for f in before['findings']}, {f['id'] for f in after['findings']}
    return {'new': sorted(new-old), 'still_present': sorted(old & new), 'no_longer_observed': sorted(old-new),
            'warning': 'No longer observed does not prove a fix; files may have been removed or excluded.'}
