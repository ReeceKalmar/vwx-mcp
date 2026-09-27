#!/usr/bin/env python3
"""
build_vs_index.py — parse the Vectorworks `vs.py` stub into a compact JSON
index of every function: arg names, arity, return type, category, one-line doc.

Purpose: signature lookup and offline call auditing. Indexing does not validate
arbitrary execute_script code or prove live compatibility.

Usage:
    python tools/build_vs_index.py <path-to-vs.py> [out.json]
Default output: vwx-plugin/vs_index.json  (deployed alongside commands.py).
"""
import ast, json, os, sys, re

def build(vs_path):
    src = open(vs_path, encoding='utf-8', errors='ignore').read()
    lines = src.splitlines(keepends=True)
    tree = ast.parse(src)
    index = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        args = [a.arg for a in node.args.args]
        n_required = len(args) - len(node.args.defaults)
        doc = ast.get_docstring(node) or ''
        category = ''
        ret = ''
        m = re.search(r'Category:\s*(.+)', doc)
        if m:
            category = m.group(1).strip()
        # return type hint from the trailing "return '<TYPE>'" in the stub
        # Avoid rescanning the entire 1.6 MB stub once per function.
        fsrc = ''.join(lines[node.lineno - 1:node.end_lineno])
        rm = re.search(r"return\s*\(?\s*'([^']+)'", fsrc)
        if rm:
            ret = rm.group(1)
        # first meaningful doc line (skip the Python:/VectorScript: signature lines)
        summary = ''
        for line in doc.splitlines():
            s = line.strip()
            if s and not s.startswith(('Python:', 'VectorScript:', 'Category:')):
                summary = s
                break
        index[node.name] = {
            'args': args,
            'arity': len(args),
            'required': n_required,
            'ret': ret,
            'cat': category,
            'doc': summary[:200],
        }
    return index

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    vs_path = sys.argv[1]
    here = os.path.dirname(os.path.abspath(__file__))
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(here, '..', 'vwx-plugin', 'vs_index.json')
    idx = build(vs_path)
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(idx, f, ensure_ascii=False, separators=(',', ':'))
    cats = {}
    for v in idx.values():
        cats[v['cat']] = cats.get(v['cat'], 0) + 1
    print('indexed %d functions -> %s' % (len(idx), os.path.normpath(out)))
    print('top categories:')
    for c, n in sorted(cats.items(), key=lambda kv: -kv[1])[:12]:
        print('  %4d  %s' % (n, c or '(none)'))

if __name__ == '__main__':
    main()
