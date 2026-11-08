#!/usr/bin/env python3
"""Measure how far apart the game dialect and NovaLang core are.

    python3 tools/dialect_probe.py PATH/TO/Reactor-Game

Translates the game dialect's recorded oracle programs (godot/scripts/nova/
conformance.json) to NovaLang by syntax alone (game AST -> NovaLang source,
`func` -> `def`, one statement per line), runs each on novalang.py, and
sorts the results: `same` (identical output), `output-differs`,
`result-differs` (one side errors), `both-error` (different message),
`no-syntax` (NovaLang has no way to write it), `timeout`. What is left over
after a purely syntactic translation is the semantic gap the profile switches
of M10 would have to close. Not part of the test suite: it needs a Reactor-Game
checkout. See docs/design/m10-dialect-inventory.md.
"""
import json, sys, subprocess, tempfile, os, collections
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME = sys.argv[1] if len(sys.argv) > 1 else '.'
sys.path.insert(0, os.path.join(GAME, 'reference'))
from nova_parser import parse
from nova_lexer import NovaError

class Unsupported(Exception): pass

def q(s):
    return json.dumps(s)  # NovaLang strings: double quotes, \n \t \\ \"

def ex(n):
    k = n['k']
    if k == 'num':
        v = n['v']
        if v != v or v in (float('inf'), float('-inf')): raise Unsupported('nonfinite literal')
        if v == int(v) and abs(v) < 1e15: return str(int(v))
        s = repr(v)
        if 'e' in s: raise Unsupported('exponent literal')
        return s
    if k == 'str': return q(n['v'])
    if k == 'bool': return 'true' if n['v'] else 'false'
    if k == 'null': raise Unsupported('null literal')
    if k == 'var': return n['name']
    if k == 'list': return '[' + ', '.join(ex(i) for i in n['items']) + ']'
    if k == 'dict':
        out = []
        for kn, vn in n['pairs']:
            if kn['k'] != 'str': raise Unsupported('computed dict key')
            out.append(q(kn['v']) + ': ' + ex(vn))
        return '{' + ', '.join(out) + '}'
    if k == 'func': raise Unsupported('anonymous function')
    if k == 'unary': return '(' + ('not ' if n['op'] == 'not' else '-') + ex(n['a']) + ')'
    if k == 'binary': return '(' + ex(n['a']) + ' ' + n['op'] + ' ' + ex(n['b']) + ')'
    if k == 'call': return ex(n['callee']) + '(' + ', '.join(ex(a) for a in n['args']) + ')'
    if k == 'index': return ex(n['obj']) + '[' + ex(n['idx']) + ']'
    if k == 'member': return ex(n['obj']) + '.' + n['name']
    raise Unsupported(k)

def st(n, ind=''):
    k = n['k']
    if k == 'let':
        e = n['expr']
        if e['k'] == 'func' and e['name'] == n['name']:
            body = blk(e['body'], ind)
            return '%sdef %s(%s) %s' % (ind, n['name'], ', '.join(e['params']), body)
        return '%slet %s = %s' % (ind, n['name'], ex(e))
    if k == 'assign': return '%s%s = %s' % (ind, ex(n['target']), ex(n['expr']))
    if k == 'exprstmt': return ind + ex(n['expr'])
    if k == 'block': return ind + blk(n, ind)
    if k == 'if':
        s = '%sif %s %s' % (ind, ex(n['cond']), blk(n['then'], ind))
        if n['else'] is not None:
            b = n['else']['body']
            if len(b) == 1 and b[0]['k'] == 'if':
                s += ' else ' + st(b[0], ind).lstrip()
            else:
                s += ' else ' + blk(n['else'], ind)
        return s
    if k == 'while': return '%swhile %s %s' % (ind, ex(n['cond']), blk(n['body'], ind))
    if k == 'return': return ind + 'return' + (' ' + ex(n['expr']) if n['expr'] else '')
    if k == 'break': return ind + 'break'
    if k == 'continue': return ind + 'continue'
    if k == 'import':
        if not n['alias']: raise Unsupported('bare import')
        return '%simport %s as %s' % (ind, q(n['path']), n['alias'])
    raise Unsupported(k)

def blk(b, ind):
    inner = '\n'.join(st(s, ind + '  ') for s in b['body'])
    return '{\n%s\n%s}' % (inner, ind) if inner else '{\n%s}' % ind

def translate(src):
    prog = parse(src)
    return '\n'.join(st(s) for s in prog.statements) + '\n'

def main():
    d = json.load(open(os.path.join(GAME, 'godot/scripts/nova/conformance.json')))
    nova = [sys.executable, os.path.join(ROOT, 'novalang.py')]
    res = collections.OrderedDict()
    for c in d['cases']:
        try:
            out = translate(c['source'])
        except NovaError as e:
            res[c['name']] = ('oracle-error-case', str(e)); continue
        except Unsupported as e:
            res[c['name']] = ('no-syntax', str(e)); continue
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, 'p.nova'); open(p, 'w').write(out)
            try:
                r = subprocess.run(nova + [p], capture_output=True, text=True, cwd=tmp, timeout=5)
            except subprocess.TimeoutExpired:
                res[c['name']] = ('timeout', 'never stops: no step budget'); continue
        got = r.stdout.splitlines()
        want = c['output']
        if r.returncode == 0 and c['ok'] and got == want: res[c['name']] = ('same', '')
        elif r.returncode == 0 and c['ok']: res[c['name']] = ('output-differs', 'want %r got %r' % (want, got))
        elif not c['ok'] and r.returncode != 0: res[c['name']] = ('both-error', 'want %r got %r' % (c['error'], (r.stderr or r.stdout).strip()[:120]))
        else: res[c['name']] = ('result-differs', 'want ok=%s %r got rc=%d %r' % (c['ok'], c['error'] or want, r.returncode, (r.stderr or r.stdout).strip()[:120]))
    cnt = collections.Counter(v[0] for v in res.values())
    print(dict(cnt))
    for k, v in res.items(): print('%-34s %-18s %s' % (k, v[0], v[1][:170]))
if __name__ == "__main__":
    main()
