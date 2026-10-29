"""Static, cited source structure. Import edges are not runtime attack paths."""
import ast
import hashlib
import posixpath
import re
from pathlib import PurePosixPath


def build_architecture(files, findings):
    nodes, edges, routes, unresolved, failures = [], [], [], [], []
    python_modules = {}
    for path in files:
        if path.endswith('.py'):
            module = path[:-3].replace('/', '.')
            python_modules[module.removesuffix('.__init__')] = path
    def resolve_python(module):
        candidates = {path for name, path in python_modules.items()
                      if name == module or name.endswith('.' + module)}
        return next(iter(candidates)) if len(candidates) == 1 else None
    def edge(source, target, line):
        if source != target:
            edges.append({'source': source, 'target': target, 'kind': 'imports',
                          'evidence': {'file': source, 'line': line}})
    def route(path, function, line, method):
        routes.append({'id': hashlib.sha256(f'{path}:{line}:{function}'.encode()).hexdigest()[:20],
                       'file': path, 'line': line, 'function': function,
                       'method': method.upper(), 'kind': 'route declaration candidate',
                       'exposure': 'not_verified', 'authentication': 'not_verified'})
    for path, source in sorted(files.items()):
        counts = sum(1 for finding in findings if finding['file'] == path)
        parts = set(PurePosixPath(path).parts)
        role = 'tests' if any(p in {'tests', 'test', '__tests__'} for p in parts) or PurePosixPath(path).name.startswith('test_') else (
            'interface' if path.endswith(('.jsx', '.tsx')) else
            'storage' if parts & {'storage', 'models', 'migrations'} else
            'service' if parts & {'services', 'api', 'routes', 'controllers'} else 'module')
        nodes.append({'id': path, 'label': PurePosixPath(path).name, 'role': role,
                      'language': 'Python' if path.endswith('.py') else 'JavaScript / TypeScript',
                      'finding_count': counts, 'line_count': len(source.splitlines()),
                      'source_sha256': hashlib.sha256(source.encode()).hexdigest()})
        if path.endswith('.py'):
            try:
                tree = ast.parse(source)
                if sum(1 for _ in ast.walk(tree)) > 50000:
                    failures.append(path)
                    continue
            except (SyntaxError, RecursionError):
                failures.append(path)
                continue
            for item in ast.walk(tree):
                if isinstance(item, (ast.Import, ast.ImportFrom)):
                    if isinstance(item, ast.Import):
                        imports = [alias.name for alias in item.names]
                    else:
                        package = path[:-3].replace('/', '.').split('.')
                        if not path.endswith('/__init__.py'): package = package[:-1]
                        if item.level:
                            prefix = package[:max(0, len(package) - item.level + 1)]
                            base = '.'.join(prefix + ([item.module] if item.module else []))
                        else: base = item.module or ''
                        imports = [base + '.' + alias.name if base else alias.name for alias in item.names]
                        if base: imports.append(base)
                    matched = False
                    for module in imports:
                        target = resolve_python(module)
                        if target:
                            edge(path, target, item.lineno)
                            matched = True
                    if not matched:
                        unresolved.append({'file': path, 'line': item.lineno, 'kind': 'external or unresolved Python import'})
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    function_routes = []
                    for decorator in item.decorator_list:
                        if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute): continue
                        method = decorator.func.attr
                        if method not in {'get', 'post', 'put', 'patch', 'delete', 'route', 'websocket', 'options', 'head'}: continue
                        if not decorator.args or not isinstance(decorator.args[0], ast.Constant) or not isinstance(decorator.args[0].value, str) or not decorator.args[0].value.startswith('/'): continue
                        route(path, item.name, decorator.lineno, method)
                        function_routes.append(routes[-1]['id'])
                    # Containment is useful context, but does not establish input flow.
                    for finding in findings:
                        if finding['file'] == path and item.lineno <= finding['line'] <= item.end_lineno:
                            finding.setdefault('containing_functions', []).append(item.name)
                            if function_routes:
                                finding.setdefault('route_declarations', []).extend(function_routes)
        else:
            # Literal import/require candidates only; no JS execution or parser claim.
            for line_number, line in enumerate(source.splitlines(), 1):
                match = re.match(r'''\s*(?:import\s+(?:.*?\s+from\s+)?|export\s+.*?\s+from\s+)["']([^"']+)["']''', line)
                if not match: continue
                module = match.group(1)
                if module.startswith('.'):
                    base = posixpath.normpath(posixpath.join(posixpath.dirname(path), module))
                    candidates = [base] + [base + extension for extension in ('.js', '.jsx', '.ts', '.tsx')] + [base + '/index' + extension for extension in ('.js', '.jsx', '.ts', '.tsx')]
                    targets = [candidate for candidate in candidates if candidate in files]
                    if len(targets) == 1:
                        edge(path, targets[0], line_number)
                        continue
                unresolved.append({'file': path, 'line': line_number, 'kind': 'external or unresolved JS import candidate'})
    unique_edges = {(e['source'], e['target'], e['evidence']['line']): e for e in edges}
    unique_routes = {r['id']: r for r in routes}
    return {'version': 'static-structure-v1', 'nodes': nodes,
            'edges': list(unique_edges.values()), 'routes': list(unique_routes.values()),
            'unresolved_import_count': len(unresolved), 'parse_failures': failures,
            'explanation': 'Boxes are source files, grouped by a path-based role. Arrows are resolved imports with source line evidence. They do not show network traffic, function calls or exploitability.',
            'unknowns': ['Runtime deployment and internet exposure', 'Authentication and authorization effectiveness',
                         'Input flow between modules', 'Dependencies with known vulnerabilities',
                         'AI prompt injection and agent tool permissions require separate review'],
            'coverage': 'Python AST imports and route decorators; literal JS/TS imports are heuristic. Unsupported files, dynamic imports, aliases and language features can leave gaps.'}
