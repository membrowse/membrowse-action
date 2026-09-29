# pylint: disable=protected-access
"""
Extends ``itanium_demangler`` with productions it does not support:

* local names        ``Z <encoding> E <entity> [<discriminator>]``
* closure types      ``Ul <type>+ E [<n>] _``      (lambdas)
* unnamed types      ``Ut [<n>] _``
* expressions        ``X <expression> E``          (e.g. SFINAE template args)
* decltype           ``Dt <expression> E`` / ``DT <expression> E``

The upstream library raises ``NotImplementedError`` for the first three in
``_parse_name``. We install a wrapper that tries the original first and, on
``NotImplementedError``, restores the cursor and dispatches to our own
handlers. Expressions and decltype are raised from ``_parse_type``; that
wrapper checks the next bytes and handles them before calling the original.
Module-level rebind of ``itanium_demangler._parse_name`` / ``_parse_type``
means recursive calls inside the library also see the patched versions.

Accessing the library's underscore-prefixed functions is intentional — this
is an extension, not a client of the public API — so ``protected-access`` is
disabled module-wide.
"""

import re
from collections import namedtuple

import itanium_demangler as _itd

_orig_parse_name = _itd._parse_name

_DISCRIM_RE = re.compile(r"_(\d)|__(\d+)_")


def _snapshot(cursor):
    return cursor._pos, dict(cursor._substs)


def _restore(cursor, snap):
    cursor._pos, cursor._substs = snap[0], dict(snap[1])


def _parse_encoding_until_e(cursor):  # pylint: disable=too-many-return-statements
    """Like ``_itd._parse_encoding`` but terminated by ``E`` instead of EOF."""
    cursor._at_encoding_name = True
    name = _itd._parse_name(cursor)
    if name is None:
        return None
    if cursor.accept('E'):
        return name

    if (name.kind == 'qual_name'
            and name.value[-1].kind == 'tpl_args'
            and name.value[-2].kind not in ('ctor', 'dtor', 'oper_cast')):
        ret_ty = _itd._parse_type(cursor)
        if ret_ty is None:
            return None
    else:
        ret_ty = None

    arg_tys = []
    while not cursor.accept('E'):
        if cursor.at_end():
            return None
        arg_ty = _itd._parse_type(cursor)
        if arg_ty is None:
            return None
        arg_tys.append(arg_ty)

    if arg_tys:
        func = _itd.FuncNode('func', name, tuple(arg_tys), ret_ty)
        return _itd._expand_template_args(func)
    return name


def _consume_optional_discriminator(cursor):
    cursor.match(_DISCRIM_RE)


def _read_trailing_number(cursor):
    """Consume digits from the cursor; return ``n+1``, or ``0`` if none.

    Itanium ABI numbers closure/unnamed types as: missing → #1, ``0`` → #2,
    ``k`` → #(k+2). Returning ``n+1`` when digits are present and ``0``
    when absent lets callers do a uniform ``+ 1`` to produce the final
    display number.
    """
    digits = ''
    while (cursor._pos < len(cursor._raw)
           and cursor._raw[cursor._pos].isdigit()):
        digits += cursor._raw[cursor._pos]
        cursor._pos += 1
    return int(digits) + 1 if digits else 0


def _parse_closure_type(cursor):
    """``Ul <type>+ E [<n>] _`` — build a pre-rendered ``{lambda(...)#N}`` name."""
    arg_tys = []
    while not cursor.accept('E'):
        if cursor.at_end():
            return None
        arg_ty = _itd._parse_type(cursor)
        if arg_ty is None:
            return None
        arg_tys.append(arg_ty)
    number = _read_trailing_number(cursor)
    if not cursor.accept('_'):
        return None

    sig = ', '.join(str(t) for t in arg_tys) if arg_tys else ''
    node = _itd.Node('name', f'{{lambda({sig})#{number + 1}}}')
    cursor.add_subst(node)
    return node


def _parse_unnamed_type(cursor):
    """``Ut [<n>] _`` — pre-rendered ``{unnamed type#N}`` name."""
    number = _read_trailing_number(cursor)
    if not cursor.accept('_'):
        return None
    node = _itd.Node('name', f'{{unnamed type#{number + 1}}}')
    cursor.add_subst(node)
    return node


def _parse_local_name(cursor):
    """``Z <encoding> E <entity> [<discriminator>]``.

    Rendered as ``encoding::entity``. Note: substitution references in the
    enclosing function's argument list may resolve to the wrong type, because
    the upstream ``itanium_demangler`` does not count substitutions the way
    libiberty/c++filt does (it deduplicates; libiberty does not, and its
    ``T_`` handling adds the resolved type rather than the ``tpl_param``
    node). The demangled *name* is correct for symbol attribution.
    """
    encoding = _parse_encoding_until_e(cursor)
    if encoding is None:
        return None
    if cursor.accept('s'):
        entity = _itd.Node('name', 'string literal')
    else:
        entity = _itd._parse_name(cursor)
        if entity is None:
            return None
    _consume_optional_discriminator(cursor)
    return _itd.Node('qual_name', (encoding, entity))


def _parse_missing_production(cursor):
    """Dispatch to the handler for the production the original parser rejected."""
    if cursor.accept('Z'):
        return _parse_local_name(cursor)
    if cursor.accept('Ul'):
        return _parse_closure_type(cursor)
    if cursor.accept('Ut'):
        return _parse_unnamed_type(cursor)
    return None


def _is_missing_production_at(raw, pos):
    """Return True if position ``pos`` starts a Z/Ul/Ut production.

    Used to distinguish NotImplementedErrors we handle from ones we don't,
    without matching on the exception message text (which is not part of
    the library's API and can change between versions).
    """
    if pos >= len(raw):
        return False
    if raw[pos] == 'Z':
        return True
    return raw[pos:pos + 2] in ('Ul', 'Ut')


def _apply_post_name_suffixes(cursor, node, is_nested):
    """Run the ABI-tag and unscoped-template-args post-processing that
    upstream ``_parse_name`` applies to every production it returns.

    Without this, ``Ul...E_B<tag>`` leaves the ABI tag unparsed and
    ``Ul...E_I<args>E`` at top level fails to bind template args to the
    closure-type name. ``Z`` returns a ``qual_name`` and so is ineligible
    for the unscoped-template-args rule — matching upstream, which only
    applies it to ``('name', 'oper', 'oper_cast')`` nodes.
    """
    abi_tags = []
    while cursor.accept('B'):
        tag = _itd._parse_source_name(cursor)
        if tag is None:
            return None
        abi_tags.append(tag)
    if abi_tags:
        node = _itd.QualNode('abi', node, frozenset(abi_tags))

    if (not is_nested
            and node.kind in ('name', 'oper', 'oper_cast')
            and cursor.accept('I')):
        cursor.add_subst(node)  # <unscoped-template-name> ::= <substitution>
        tpl_args = _itd._parse_until_end(cursor, 'tpl_args', _itd._parse_type)
        if tpl_args is None:
            return None
        node = _itd.Node('qual_name', (node, tpl_args))
    return node


_STD_ABBREV_RE = re.compile(r"S[absiod]")


def _patched_add_subst(cursor, node):
    """Skip the one registration flagged by ``_patched_parse_name``."""
    skip = getattr(cursor, '_skip_subst', None)
    if skip is not None:
        cursor._skip_subst = None
        if node == skip:
            return
    _orig_add_subst(cursor, node)


_orig_add_subst = _itd._Cursor.add_subst


def _patched_parse_name(cursor, is_nested=False):
    at_encoding_name = getattr(cursor, '_at_encoding_name', False)
    cursor._at_encoding_name = False
    snap = _snapshot(cursor)
    std_abbrev = (cursor._raw[snap[0]:snap[0] + 2]
                  if is_nested and _STD_ABBREV_RE.match(cursor._raw, snap[0]) else None)
    try:
        node = _orig_parse_name(cursor, is_nested)
        if std_abbrev is not None and node is not None:
            # Upstream's nested-name loop registers the prefix after each
            # component, including a leading standard abbreviation such as
            # ``Ss`` in ``_ZNSs7compare...``. The ABI excludes those, so skip
            # the registration that immediately follows.
            cursor._skip_subst = _itd.Node('qual_name', tuple(node.value))
        if at_encoding_name:
            _drop_encoding_name_subst(cursor, node, len(snap[1]))
        return node
    except NotImplementedError:
        if not _is_missing_production_at(cursor._raw, snap[0]):
            raise
        _restore(cursor, snap)
        node = _parse_missing_production(cursor)
        if node is None:
            return None
        return _apply_post_name_suffixes(cursor, node, is_nested)


_itd._parse_name = _patched_parse_name
_itd._Cursor.add_subst = _patched_add_subst


# --- Expressions ------------------------------------------------------------

class ExprNode(namedtuple('ExprNode', 'kind value operands')):
    """An expression from an ``X...E`` template argument or a ``decltype``.

    ``value`` is the operator or keyword text and ``operands`` holds child
    nodes. ``map`` visits the operands, so upstream template-parameter
    expansion also substitutes ``T_`` references inside expressions.
    """

    def __str__(self):
        return _RENDERERS[self.kind](self.value, self.operands)

    def left(self):
        """Declarator prefix; expressions render in one piece."""
        return str(self)

    def right(self):
        """Declarator suffix; expressions render in one piece."""
        return ''

    def map(self, f):
        """Apply ``f`` to each operand (mirrors upstream node classes)."""
        return self._replace(operands=tuple(f(op) for op in self.operands))


_COMPOUND_KINDS = frozenset(('prefix', 'postfix', 'binary', 'ternary', 'c_cast'))


def _wrap(node):
    text = str(node)
    if isinstance(node, ExprNode) and node.kind in _COMPOUND_KINDS:
        return '(' + text + ')'
    return text


def _join(nodes):
    return ', '.join(str(n) for n in nodes)


def _render_binary(op, xs):
    text = f'{_wrap(xs[0])} {op} {_wrap(xs[1])}'
    # A bare '>' would close the enclosing template argument list.
    return '(' + text + ')' if '>' in op else text


_RENDERERS = {
    'text': lambda op, xs: op,
    'prefix': lambda op, xs: op + _wrap(xs[0]),
    'postfix': lambda op, xs: _wrap(xs[0]) + op,
    'binary': _render_binary,
    'ternary': lambda op, xs: f'{_wrap(xs[0])} ? {_wrap(xs[1])} : {_wrap(xs[2])}',
    'call': lambda op, xs: f'{_wrap(xs[0])}({_join(xs[1:])})',
    'index': lambda op, xs: f'{_wrap(xs[0])}[{xs[1]}]',
    'member': lambda op, xs: f'{_wrap(xs[0])}{op}{xs[1]}',
    'keyword': lambda op, xs: f'{op}({_join(xs)})',
    'named_cast': lambda op, xs: f'{op}<{xs[0]}>({xs[1]})',
    'c_cast': lambda op, xs: f'({xs[0]}){_wrap(xs[1])}',
    'construct': lambda op, xs: f'{xs[0]}({_join(xs[1:])})',
    'pack_expansion': lambda op, xs: _wrap(xs[0]) + '...',
    'throw': lambda op, xs: 'throw' + (' ' + str(xs[0]) if xs else ''),
    'global': lambda op, xs: '::' + str(xs[0]),
    'fold_left': lambda op, xs: f'(... {op} {xs[0]})',
    'fold_right': lambda op, xs: f'({xs[0]} {op} ...)',
    'fold_binary': lambda op, xs: f'({xs[0]} {op} ... {op} {xs[1]})',
}

_PREFIX_OPS = {
    'ps': '+', 'ng': '-', 'ad': '&', 'de': '*', 'co': '~', 'nt': '!',
    'pp_': '++', 'mm_': '--', 'dl': 'delete ', 'da': 'delete[] ',
}
_POSTFIX_OPS = {'pp': '++', 'mm': '--'}
_BINARY_OPS = {
    'pl': '+', 'mi': '-', 'ml': '*', 'dv': '/', 'rm': '%', 'an': '&',
    'or': '|', 'eo': '^', 'aS': '=', 'pL': '+=', 'mI': '-=', 'mL': '*=',
    'dV': '/=', 'rM': '%=', 'aN': '&=', 'oR': '|=', 'eO': '^=', 'ls': '<<',
    'rs': '>>', 'lS': '<<=', 'rS': '>>=', 'eq': '==', 'ne': '!=', 'lt': '<',
    'gt': '>', 'le': '<=', 'ge': '>=', 'ss': '<=>', 'aa': '&&', 'oo': '||',
    'cm': ',', 'pm': '->*',
}
_TYPE_KEYWORDS = {'st': 'sizeof', 'at': 'alignof', 'ti': 'typeid'}
_EXPR_KEYWORDS = {
    'sz': 'sizeof', 'az': 'alignof', 'te': 'typeid', 'nx': 'noexcept',
    'sZ': 'sizeof...',
}
_NAMED_CASTS = {
    'dc': 'dynamic_cast', 'sc': 'static_cast', 'cc': 'const_cast',
    'rc': 'reinterpret_cast',
}

_FUNC_PARAM_RE = re.compile(r"[rVK]*(\d*)_")
_FUNC_PARAM_LEVEL_RE = re.compile(r"\d+p[rVK]*(\d*)_")


def _peek_digit(cursor):
    return (cursor._pos < len(cursor._raw)
            and cursor._raw[cursor._pos].isdigit())


def _parse_exprs_until_e(cursor):
    exprs = []
    while not cursor.accept('E'):
        if cursor.at_end():
            return None
        expr = _parse_expression(cursor)
        if expr is None:
            return None
        exprs.append(expr)
    return exprs


def _parse_types_until_e(cursor):
    types = []
    while not cursor.accept('E'):
        if cursor.at_end():
            return None
        ty = _itd._parse_type(cursor)
        if ty is None:
            return None
        types.append(ty)
    return types


def _with_template_args(cursor, node):
    if cursor.accept('I'):
        args = _itd._parse_until_end(cursor, 'tpl_args', _itd._parse_type)
        if args is None:
            return None
        return _itd.Node('qual_name', (node, args))
    return node


def _flatten(node):
    return list(node.value) if node.kind == 'qual_name' else [node]


def _parse_template_param(cursor):
    """``T [<n>] _ [<template-args>]``.

    Parsed here rather than via upstream ``_parse_name``, which consumes a
    following ``I`` without parsing the template args after a ``T_``.
    """
    cursor.accept('T')
    seq_id = _itd._parse_seq_id(cursor)
    if seq_id is None:
        return None
    node = _itd.Node('tpl_param', seq_id)
    cursor.add_subst(node)
    if cursor._raw.startswith('I', cursor._pos):
        node = _with_template_args(cursor, node)
        if node is not None:
            cursor.add_subst(node)
    return node


def _parse_simple_id(cursor):
    """``<source-name> [<template-args>]``."""
    if not _peek_digit(cursor):
        return None
    name = _itd._parse_source_name(cursor)
    if name is None:
        return None
    return _with_template_args(cursor, _itd.Node('name', name))


def _parse_base_unresolved_name(cursor):
    """``<simple-id>`` | ``on <operator-name> [<template-args>]`` | ``dn <destructor-name>``."""
    if cursor.accept('on'):
        name = _itd._parse_name(cursor, is_nested=True)
        if name is None or name.kind not in ('oper', 'oper_cast'):
            return None
        return _with_template_args(cursor, name)
    if cursor.accept('dn'):
        if _peek_digit(cursor):
            target = _parse_simple_id(cursor)
        else:
            target = _itd._parse_type(cursor)
        return None if target is None else ExprNode('prefix', '~', (target,))
    return _parse_simple_id(cursor)


def _parse_unresolved_type(cursor):
    if cursor._raw.startswith('T', cursor._pos):
        return _parse_template_param(cursor)
    # Substitutions and decltype per the ABI; GCC also emits arbitrary
    # types here (e.g. ``srSt7is_sameI...E5value``), which _parse_type covers.
    return _itd._parse_type(cursor)


def _parse_unresolved_name(cursor, _code):  # pylint: disable=too-many-return-statements
    """Everything after ``sr`` in an ``<unresolved-name>``.

    ``srN <unresolved-type> <simple-id>+ E <base>``,
    ``sr <simple-id>+ E <base>``, or ``sr <unresolved-type> <base>``.
    """
    if cursor.accept('N'):
        qual = _parse_unresolved_type(cursor)
        if qual is None:
            return None
        levels_end_with_e = True
    elif _peek_digit(cursor):
        qual = None
        levels_end_with_e = True
    else:
        qual = _parse_unresolved_type(cursor)
        if qual is None:
            return None
        levels_end_with_e = False
    parts = _flatten(qual) if qual is not None else []

    # Each level registers its prefix before and after its template args,
    # matching libiberty's substitution numbering for nested prefixes.
    while levels_end_with_e and not cursor.accept('E'):
        if not _peek_digit(cursor):
            return None
        name = _itd._parse_source_name(cursor)
        if name is None:
            return None
        parts.append(_itd.Node('name', name))
        cursor.add_subst(_itd.Node('qual_name', tuple(parts)))
        if cursor.accept('I'):
            args = _itd._parse_until_end(cursor, 'tpl_args', _itd._parse_type)
            if args is None:
                return None
            parts.append(args)
            cursor.add_subst(_itd.Node('qual_name', tuple(parts)))

    base = _parse_base_unresolved_name(cursor)
    if base is None:
        return None
    return _itd.Node('qual_name', tuple(parts + _flatten(base)))


def _parse_function_param(cursor, code):
    """``fp <CV> [<n>] _`` or ``fL <level> p <CV> [<n>] _`` → ``{parm#N}``."""
    match = cursor.match(_FUNC_PARAM_RE if code == 'fp' else _FUNC_PARAM_LEVEL_RE)
    if match is None:
        return None
    digits = match.group(1)
    return ExprNode('text', f'{{parm#{int(digits) + 2 if digits else 1}}}', ())


def _operands(cursor, count):
    ops = []
    for _ in range(count):
        op = _parse_expression(cursor)
        if op is None:
            return None
        ops.append(op)
    return tuple(ops)


def _expr_node(kind, value, operands):
    return None if operands is None else ExprNode(kind, value, operands)


def _parse_prefix(cursor, code):
    return _expr_node('prefix', _PREFIX_OPS[code], _operands(cursor, 1))


def _parse_postfix(cursor, code):
    return _expr_node('postfix', _POSTFIX_OPS[code], _operands(cursor, 1))


def _parse_binary(cursor, code):
    return _expr_node('binary', _BINARY_OPS[code], _operands(cursor, 2))


def _parse_expr_keyword(cursor, code):
    return _expr_node('keyword', _EXPR_KEYWORDS[code], _operands(cursor, 1))


def _parse_type_keyword(cursor, code):
    ty = _itd._parse_type(cursor)
    return None if ty is None else ExprNode('keyword', _TYPE_KEYWORDS[code], (ty,))


def _parse_named_cast(cursor, code):
    ty = _itd._parse_type(cursor)
    if ty is None:
        return None
    expr = _parse_expression(cursor)
    return None if expr is None else ExprNode('named_cast', _NAMED_CASTS[code], (ty, expr))


def _parse_conversion(cursor, _code):
    """``cv <type> <expression>`` or ``cv <type> _ <expression>* E``."""
    ty = _itd._parse_type(cursor)
    if ty is None:
        return None
    if cursor.accept('_'):
        args = _parse_exprs_until_e(cursor)
        return None if args is None else ExprNode('construct', '', (ty, *args))
    expr = _parse_expression(cursor)
    return None if expr is None else ExprNode('c_cast', '', (ty, expr))


def _parse_call(cursor, _code):
    exprs = _parse_exprs_until_e(cursor)
    return ExprNode('call', '', tuple(exprs)) if exprs else None


def _parse_member(cursor, code):
    op = {'dt': '.', 'pt': '->', 'ds': '.*'}[code]
    return _expr_node('member', op, _operands(cursor, 2))


def _parse_fold(cursor, code):
    op = _BINARY_OPS.get(cursor._raw[cursor._pos:cursor._pos + 2])
    if op is None:
        return None
    cursor._pos += 2
    if code in ('fL', 'fR'):
        return _expr_node('fold_binary', op, _operands(cursor, 2))
    kind = 'fold_left' if code == 'fl' else 'fold_right'
    return _expr_node(kind, op, _operands(cursor, 1))


def _parse_fl(cursor, code):
    # 'fL' is a function parameter when followed by a level number,
    # otherwise a binary left fold.
    if _peek_digit(cursor):
        return _parse_function_param(cursor, code)
    return _parse_fold(cursor, code)


def _parse_sizeof_pack_args(cursor, _code):
    args = _parse_types_until_e(cursor)
    return None if args is None else ExprNode('keyword', 'sizeof...', tuple(args))


_EXPR_HANDLERS = {
    **{code: _parse_prefix for code in _PREFIX_OPS},
    **{code: _parse_postfix for code in _POSTFIX_OPS},
    **{code: _parse_binary for code in _BINARY_OPS},
    **{code: _parse_expr_keyword for code in _EXPR_KEYWORDS},
    **{code: _parse_type_keyword for code in _TYPE_KEYWORDS},
    **{code: _parse_named_cast for code in _NAMED_CASTS},
    'ix': lambda c, _: _expr_node('index', '', _operands(c, 2)),
    'qu': lambda c, _: _expr_node('ternary', '', _operands(c, 3)),
    'cl': _parse_call,
    'cv': _parse_conversion,
    'dt': _parse_member,
    'pt': _parse_member,
    'ds': _parse_member,
    'sr': _parse_unresolved_name,
    'gs': lambda c, _: _expr_node('global', '', _operands(c, 1)),
    'sp': lambda c, _: _expr_node('pack_expansion', '', _operands(c, 1)),
    'sP': _parse_sizeof_pack_args,
    'tw': lambda c, _: _expr_node('throw', '', _operands(c, 1)),
    'tr': lambda c, _: ExprNode('throw', '', ()),
    'fp': _parse_function_param,
    'fL': _parse_fl,
    'fl': _parse_fold,
    'fr': _parse_fold,
    'fR': _parse_fold,
}


def _parse_expression(cursor):
    """Parse one ``<expression>``; return ``None`` for unsupported forms."""
    raw, pos = cursor._raw, cursor._pos
    if pos >= len(raw):
        return None
    if raw[pos] == 'L':
        return _itd._parse_expr_primary(cursor)
    if raw[pos] == 'T':
        return _parse_template_param(cursor)
    if raw[pos].isdigit() or raw.startswith(('on', 'dn'), pos):
        return _parse_base_unresolved_name(cursor)
    # Prefix increment/decrement ('pp_') must win over postfix ('pp').
    code = raw[pos:pos + 3] if raw.startswith(('pp_', 'mm_'), pos) else raw[pos:pos + 2]
    handler = _EXPR_HANDLERS.get(code)
    if handler is None:
        return None
    cursor._pos += len(code)
    return handler(cursor, code)


_orig_parse_type = _itd._parse_type


def _patched_parse_type(cursor):
    raw, pos = cursor._raw, cursor._pos
    if raw.startswith('I', pos):
        # Old-style argument pack ``I <template-arg>* E`` (GCC < 4.7 form of
        # ``J...E``). Upstream parses it as template args and registers it as
        # a substitution, which libiberty does not, shifting later ``S<n>_``.
        cursor._pos += 1
        return _itd._parse_until_end(cursor, 'tpl_arg_pack', _itd._parse_type)
    if raw.startswith('X', pos):
        cursor._pos += 1
        expr = _parse_expression(cursor)
        if expr is None or not cursor.accept('E'):
            return None
        return expr
    if raw.startswith(('Dt', 'DT'), pos):
        cursor._pos += 2
        expr = _parse_expression(cursor)
        if expr is None or not cursor.accept('E'):
            return None
        node = ExprNode('keyword', 'decltype', (expr,))
        cursor.add_subst(node)
        return node
    return _orig_parse_type(cursor)


_itd._parse_type = _patched_parse_type


# --- Encoding-name substitutions ----------------------------------------------

_orig_parse_encoding = _itd._parse_encoding


def _patched_parse_encoding(cursor):
    cursor._at_encoding_name = True
    return _orig_parse_encoding(cursor)


def _drop_encoding_name_subst(cursor, node, substs_before):
    """Undo upstream registering a function's own template-id as a substitution.

    For ``_ZSt4swapI...E`` upstream adds ``std::swap<...>`` to the
    substitution table; per the ABI only ``std::swap`` is a candidate when
    the template-id names the function rather than a type, so every later
    ``S<n>_`` would resolve one entry off.
    """
    substs = cursor._substs
    last = len(substs) - 1
    if (len(substs) > substs_before
            and node is not None
            and node.kind == 'qual_name'
            and node.value[-1].kind == 'tpl_args'
            and substs.get(last) == node):
        del substs[last]


# --- Reference collapsing ---------------------------------------------------

_REF_KINDS = ('lvalue', 'rvalue')


def _collapse_references(node):
    """Apply C++ reference collapsing: ``T& &``, ``T& &&``, ``T&& &`` → ``T&``;
    ``T&& &&`` → ``T&&``.

    Needed after template-argument expansion, where a forwarding reference
    ``T&&`` with ``T = X&`` would otherwise render as ``X&&&``.
    """
    node = node.map(_collapse_references)
    if node.kind in _REF_KINDS and getattr(node.value, 'kind', None) in _REF_KINDS:
        inner = node.value
        kind = 'rvalue' if node.kind == inner.kind == 'rvalue' else 'lvalue'
        return _itd.Node(kind, inner.value)
    return node


_orig_expand_template_args = _itd._expand_template_args


def _patched_expand_template_args(func):
    return _collapse_references(_orig_expand_template_args(func))


_itd._expand_template_args = _patched_expand_template_args

_itd._parse_encoding = _patched_parse_encoding
