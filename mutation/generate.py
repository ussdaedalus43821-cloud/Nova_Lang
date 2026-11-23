#!/usr/bin/env python3
"""Choose the mutants: small deliberate bugs in the code that matters most, with a fixed seed so the choice can be repeated.

    python3 mutation/generate.py [--seed 20261117] [--total 200]

Writes mutation/mutants.json. Nothing in the repository is changed: a mutant is a description (file, line, column, old text, new text);
mutation/run_mutants.py applies it to a copy of the repository.
"""
import argparse
import ast
import io
import json
import os
import random
import re
import sys
import tokenize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PY = "novalang.py"
NOVA = "novalang.nova"
DATE = "lib/std/date.nova"

# area -> {file: (symbols or line filters)}; a symbol is a Python function, method or class, or a NovaLang function, whose lines are the region
AREAS = {
    "sandbox": {"quota": 36, "nova_quota": 8,
                "py_symbols": ["inside_folder", "real_path", "Capabilities", "Interpreter.check_copy_destination", "Interpreter.check_call_arguments",
                               "Interpreter.check_result_size", "Interpreter.check_file_append", "Interpreter.delete_file", "_verify_final_path",
                               "native_check_size", "resolve_python_path", "check_installed", "Interpreter.check_package_file",
                               "Interpreter.lookup_builtin"],
                "nova_symbols": ["cap_has", "builtin_defined", "sandbox_inside", "check_builtin_paths", "check_builtin_limits", "check_result_size",
                                 "configure_sandbox", "sandbox_norm"]},
    "nesting": {"quota": 18, "nova_quota": 4,
                "py_symbols": ["Parser.enter_nesting", "Parser.enter_chain", "check_tree_depth"],
                "py_line_filter": ("Parser", re.compile(r"self\.nesting|self\.chain|check_tree_depth\(")),
                "py_const_lines": re.compile(r"^(NESTING_LIMIT|TREE_DEPTH_LIMIT) = "),
                "nova_symbols": ["nesting_enter", "nesting_leave"]},
    "steps": {"quota": 40, "nova_quota": 10,
              "py_symbols": ["Interpreter.step", "Interpreter.step_slow", "Interpreter.charge", "Interpreter.check_interval", "Interpreter.check_time",
                             "operand_work", "membership_work", "Limits", "RegexMeter.tick"],
              "py_line_filter": ("*", re.compile(r"CONSTANT_WORK|self\.charge\(|interpreter\.charge\(|self\.step\(node|interpreter\.step\(|membership_work\(|operand_work\(")),
              "py_const_lines": re.compile(r"^(WORK_PER_STEP|CHARGE_FLOOR|WORK_CHECK_UNITS|CONSTANT_WORK|REGEX_UNIT) = "),
              "nova_symbols": ["charge", "native_work", "step_slow", "count_step", "begin_counters", "check_time", "operand_work", "membership_work"]},
    "parser": {"quota": 34, "nova_quota": 0,
               "py_symbols": ["Parser"], "py_exclude": re.compile(r"self\.nesting|self\.chain|check_tree_depth|enter_nesting|enter_chain")},
    "vm": {"quota": 36, "nova_quota": 0,
           "py_symbols": ["binary_operation", "compare_operation", "unary_operation"],
           "execute_branches": re.compile(r"^\s+elif op == (ADD_|SUB_|MUL_|DIV_|MOD_|FLOORDIV_|DSLASH_|LT_|GT_|LE_|GE_|EQ_|NE_|NEG_|POS_|NOT_|IN_):")},
    "date": {"quota": 36, "nova_quota": 12,
             "py_name_prefixes": ("date_", "native_date_"),
             "nova_file": DATE},
}

CMP = {"<": "<=", "<=": "<", ">": ">=", ">=": ">", "==": "!=", "!=": "=="}
ARITH = {"+": "-", "-": "+", "*": "+", "//": "/", "%": "//"}


def read(path):
    with open(os.path.join(ROOT, path), "r", encoding="utf-8") as handle:
        return handle.read()


def python_symbol_lines(source, names, prefixes=()):
    tree = ast.parse(source)
    spans = {}

    def walk(node, prefix=""):
        for child in getattr(node, "body", []):
            if isinstance(child, (ast.FunctionDef, ast.ClassDef)):
                spans[prefix + child.name] = (child.lineno, child.end_lineno)
                if isinstance(child, ast.ClassDef):
                    walk(child, prefix + child.name + ".")
    walk(tree)
    lines = set()
    for name in names:
        if name in spans:
            lines.update(range(spans[name][0], spans[name][1] + 1))
        else:
            raise SystemExit("symbol not found: " + name)
    for name, (a, b) in spans.items():
        if prefixes and "." not in name and name.startswith(prefixes):
            lines.update(range(a, b + 1))
    return lines


def nova_symbol_lines(source, names):
    lines_text = source.split("\n")
    spans = {}
    for index, text in enumerate(lines_text):
        match = re.match(r"def (\w+)\(", text)
        if match:
            end = index
            while end < len(lines_text) and lines_text[end] != "}":
                end += 1
            spans[match.group(1)] = (index + 1, end + 1)
    selected = set()
    for name in names:
        if name not in spans:
            raise SystemExit("nova function not found: " + name)
        selected.update(range(spans[name][0], spans[name][1] + 1))
    return selected


def python_candidates(source, allowed_lines):
    """Mutations of the allowed lines of a Python file: operators, constants, and, or, True, False, a deleted statement, an inverted condition."""
    out = []
    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    previous = None
    for token in tokens:
        kind, text, (row, column), (end_row, end_column), _ = token
        if row in allowed_lines and row == end_row:
            if kind == tokenize.OP and text in CMP:
                out.append((row, column, end_column, text, CMP[text], "comparison"))
            elif kind == tokenize.OP and text in ARITH and previous is not None and (
                    previous[0] in (tokenize.NAME, tokenize.NUMBER, tokenize.STRING) or previous[1] in (")", "]")):
                out.append((row, column, end_column, text, ARITH[text], "arithmetic"))
            elif kind == tokenize.NAME and text in ("and", "or"):
                out.append((row, column, end_column, text, "or" if text == "and" else "and", "and/or"))
            elif kind == tokenize.NAME and text in ("True", "False"):
                out.append((row, column, end_column, text, "False" if text == "True" else "True", "boolean"))
            elif kind == tokenize.NUMBER and re.fullmatch(r"\d+", text):
                number = int(text)
                out.append((row, column, end_column, text, str(number + 1), "constant +1"))
                if number >= 1:
                    out.append((row, column, end_column, text, str(number - 1), "constant -1"))
        if kind not in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT):
            previous = token
    lines = source.split("\n")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.While, ast.IfExp)) and node.test.lineno == node.test.end_lineno and node.test.lineno in allowed_lines:
            segment = lines[node.test.lineno - 1][node.test.col_offset:node.test.end_col_offset]
            if not segment.startswith("not "):
                out.append((node.test.lineno, node.test.col_offset, node.test.end_col_offset, segment, "not (" + segment + ")", "inverted condition"))
        if isinstance(node, (ast.Expr, ast.Assign, ast.AugAssign, ast.Raise)) and node.lineno == node.end_lineno and node.lineno in allowed_lines:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                continue          # a docstring
            text = lines[node.lineno - 1]
            out.append((node.lineno, node.col_offset, len(text.rstrip()), text.strip(), "pass", "deleted statement"))
    return out


def strip_strings(text):
    """`text` with the contents of string literals blanked (same length), and the comment cut off."""
    out, in_string, i = [], False, 0
    while i < len(text):
        ch = text[i]
        if in_string:
            if ch == "\\":
                out.append("  ")
                i += 2
                continue
            out.append('"' if ch == '"' else " ")
            if ch == '"':
                in_string = False
        else:
            if ch == "#":
                break
            out.append(ch)
            if ch == '"':
                in_string = True
        i += 1
    return "".join(out)


def nova_candidates(source, allowed_lines):
    out = []
    lines = source.split("\n")
    for number in sorted(allowed_lines):
        text = lines[number - 1]
        code = strip_strings(text)
        if not code.strip():
            continue
        for match in re.finditer(r"<=|>=|==|!=|<|>", code):
            if code[match.start() - 1:match.start()] in "<>=!" and match.start() > 0 and match.group() in "<>" and code[match.start() - 1] in "<>=!":
                continue
            out.append((number, match.start(), match.end(), match.group(), CMP[match.group()], "comparison"))
        for match in re.finditer(r"\b(and|or)\b", code):
            out.append((number, match.start(), match.end(), match.group(), "or" if match.group() == "and" else "and", "and/or"))
        for match in re.finditer(r"\b(true|false)\b", code):
            out.append((number, match.start(), match.end(), match.group(), "false" if match.group() == "true" else "true", "boolean"))
        for match in re.finditer(r"(?<![\w.\"])\d+(?![\w.\"])", code):
            value = int(match.group())
            out.append((number, match.start(), match.end(), match.group(), str(value + 1), "constant +1"))
            if value >= 1:
                out.append((number, match.start(), match.end(), match.group(), str(value - 1), "constant -1"))
        for match in re.finditer(r"(?<=\w) ([+\-*]|//|%) (?=[\w(])", code):
            symbol = match.group(1)
            out.append((number, match.start(1), match.end(1), symbol, ARITH.get(symbol, "+"), "arithmetic"))
        condition = re.match(r"^(\s*(?:\} else )?(?:if|while) )(.*)( \{)\s*$", code)
        if condition and "not (" not in condition.group(2):
            start, end = len(condition.group(1)), len(condition.group(1)) + len(condition.group(2))
            segment = text[start:end]
            out.append((number, start, end, segment, "not (" + segment + ")", "inverted condition"))
        stripped = code.strip()
        if (re.match(r"^(let [A-Za-z_]\w* = .+|[A-Za-z_][\w\[\]\"\.]* = .+|[A-Za-z_]\w*\(.*\))$", stripped) and not stripped.endswith("{")
                and not stripped.startswith("def ")):
            out.append((number, len(text) - len(text.lstrip()), len(text.rstrip()), text.strip(), "0", "deleted statement"))
    return out


def region(area, spec, source, lines_spec_key="py"):
    pass


def line_matches(source, pattern, within=None):
    lines = source.split("\n")
    return {number + 1 for number, text in enumerate(lines) if pattern.search(text)}


def build_pool():
    py_source, nova_source, date_source = read(PY), read(NOVA), read(DATE)
    pools = {}
    for area, spec in AREAS.items():
        allowed_py, allowed_nova, nova_file, nova_text = set(), set(), None, None
        if "py_symbols" in spec or "py_name_prefixes" in spec:
            allowed_py = python_symbol_lines(py_source, spec.get("py_symbols", []), spec.get("py_name_prefixes", ()))
        if "py_line_filter" in spec:
            scope, pattern = spec["py_line_filter"]
            matched = line_matches(py_source, pattern)
            if scope != "*":
                allowed_in_scope = python_symbol_lines(py_source, [scope])
                matched &= allowed_in_scope
            allowed_py |= matched
        if "py_const_lines" in spec:
            allowed_py |= line_matches(py_source, spec["py_const_lines"])
        if "execute_branches" in spec:
            lines = py_source.split("\n")
            execute = python_symbol_lines(py_source, ["execute"])
            current = False
            for number in sorted(execute):
                text = lines[number - 1]
                if re.match(r"^                elif op == ", text) or re.match(r"^                if op == ", text):
                    current = bool(spec["execute_branches"].match(text))
                if current:
                    allowed_py.add(number)
        if "py_exclude" in spec:
            lines = py_source.split("\n")
            allowed_py = {n for n in allowed_py if not spec["py_exclude"].search(lines[n - 1])}
        if spec.get("nova_symbols"):
            allowed_nova, nova_file, nova_text = nova_symbol_lines(nova_source, spec["nova_symbols"]), NOVA, nova_source
        if spec.get("nova_file"):
            nova_file, nova_text = spec["nova_file"], date_source
            allowed_nova = set(range(1, len(date_source.split("\n")) + 1))
        pools[area] = {
            "py": [(PY,) + c for c in python_candidates(py_source, allowed_py)],
            "nova": [(nova_file,) + c for c in nova_candidates(nova_text, allowed_nova)] if nova_file else [],
        }
    return pools


def apply(source, candidate):
    """The source text with one mutation applied."""
    _, row, start, end, old, new, kind = candidate[:7]
    lines = source.split("\n")
    text = lines[row - 1]
    if kind == "deleted statement":
        indent = text[:len(text) - len(text.lstrip())]
        lines[row - 1] = indent + new if candidate[0].endswith(".py") else indent + "# mutant: line deleted"
    else:
        lines[row - 1] = text[:start] + new + text[end:]
    return "\n".join(lines)


def viable(source_by_file, candidate):
    path = candidate[0]
    mutated = apply(source_by_file[path], candidate)
    try:
        if path.endswith(".py"):
            compile(mutated, path, "exec")
        else:
            import novalang
            novalang.Parser(novalang.Lexer(mutated).tokenize()).parse()
    except BaseException:
        return False
    return mutated != source_by_file[path]


def exhaustive(args):
    """Every viable mutant of the named areas (no sampling), one per distinct change, in a stable order."""
    pools = build_pool()
    sources = {PY: read(PY), NOVA: read(NOVA), DATE: read(DATE)}
    mutants, report = [], {}
    for area in args.exhaustive.split(","):
        every = list(dict.fromkeys(pools[area]["py"] + pools[area]["nova"]))
        every.sort(key=lambda c: (c[0], c[1], c[2], c[5]))
        kept = [c for c in every if viable(sources, c)]
        report[area] = {"pool": len(every), "viable": len(kept)}
        for candidate in kept:
            path, row, start, end, old, new, kind = candidate
            lines = sources[path].split("\n")
            mutants.append({"id": "X%04d" % (len(mutants) + 1), "area": area, "file": path, "line": row, "col": start, "end": end, "old": old, "new": new,
                            "kind": kind, "line_before": lines[row - 1].strip(), "line_after": apply(sources[path], candidate).split("\n")[row - 1].strip()})
    out = args.out or os.path.join(ROOT, "mutation", "mutants_exhaustive.json")
    json.dump({"exhaustive": args.exhaustive, "total": len(mutants), "per_area": report, "mutants": mutants}, open(out, "w"), indent=1)
    print("exhaustive mutants:", len(mutants), report)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20261117)
    parser.add_argument("--total", type=int, default=200)
    parser.add_argument("--exhaustive", help="comma-separated areas: take EVERY viable mutant of these areas instead of a sample (ids X0001...)")
    parser.add_argument("--out", help="write the mutants here instead of mutation/mutants.json")
    args = parser.parse_args()
    if args.exhaustive:
        return exhaustive(args)
    rng = random.Random(args.seed)
    pools = build_pool()
    sources = {PY: read(PY), NOVA: read(NOVA), DATE: read(DATE)}
    scale = args.total / 200.0
    chosen, report = [], {}
    for area, spec in AREAS.items():
        quota_py = max(1, round((spec["quota"] - spec["nova_quota"]) * scale))
        quota_nova = round(spec["nova_quota"] * scale)
        picked = {"py": 0, "nova": 0}
        for lang, quota in (("nova", quota_nova), ("py", quota_py)):
            if lang == "py":
                quota += quota_nova - picked["nova"]          # a NovaLang region too small (or without operators) gives its share to the Python code
            pool = list(dict.fromkeys(pools[area][lang]))
            rng.shuffle(pool)
            # spread over kinds: take round-robin by kind so no single operator dominates
            by_kind = {}
            for candidate in pool:
                by_kind.setdefault(candidate[6], []).append(candidate)
            order = []
            while any(by_kind.values()):
                for kind in sorted(by_kind):
                    if by_kind[kind]:
                        order.append(by_kind[kind].pop(0))
            seen_sites = set()
            for candidate in order:
                if picked[lang] >= quota:
                    break
                site = (candidate[0], candidate[1], candidate[2])
                if site in seen_sites or not viable(sources, candidate):
                    continue
                seen_sites.add(site)
                chosen.append((area, lang, candidate))
                picked[lang] += 1
        report[area] = dict(picked, pool_py=len(set(pools[area]["py"])), pool_nova=len(set(pools[area]["nova"])))
    mutants = []
    for number, (area, lang, candidate) in enumerate(chosen, 1):
        path, row, start, end, old, new, kind = candidate
        lines = sources[path].split("\n")
        mutants.append({"id": "M%03d" % number, "area": area, "file": path, "line": row, "col": start, "end": end, "old": old, "new": new,
                        "kind": kind, "line_before": lines[row - 1].strip(),
                        "line_after": apply(sources[path], candidate).split("\n")[row - 1].strip()})
    json.dump({"seed": args.seed, "total": len(mutants), "per_area": report, "mutants": mutants}, open(os.path.join(ROOT, "mutation", "mutants.json"), "w"), indent=1)
    print("mutants:", len(mutants), "seed:", args.seed)
    for area, info in report.items():
        print("  %-8s py %2d (pool %4d)  nova %2d (pool %4d)" % (area, info["py"], info["pool_py"], info["nova"], info["pool_nova"]))


if __name__ == "__main__":
    main()
