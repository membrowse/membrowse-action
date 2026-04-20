# pylint: disable=protected-access
"""
Extends ``itanium_demangler`` with the three productions it does not support:

* local names        ``Z <encoding> E <entity> [<discriminator>]``
* closure types      ``Ul <type>+ E [<n>] _``      (lambdas)
* unnamed types      ``Ut [<n>] _``

The upstream library raises ``NotImplementedError`` for these in
``_parse_name``. We install a wrapper that tries the original first and, on
``NotImplementedError``, restores the cursor and dispatches to our own
handlers. Module-level rebind of ``itanium_demangler._parse_name`` means
recursive calls inside ``_parse_encoding`` / ``_parse_type`` also see the
patched version.

Accessing the library's underscore-prefixed functions is intentional — this
is an extension, not a client of the public API — so ``protected-access`` is
disabled module-wide.
"""

import re

import itanium_demangler as _itd

_orig_parse_name = _itd._parse_name

_DISCRIM_RE = re.compile(r"_(\d)|__(\d+)_")


def _snapshot(cursor):
    return cursor._pos, dict(cursor._substs)


def _restore(cursor, snap):
    cursor._pos, cursor._substs = snap[0], dict(snap[1])


def _parse_encoding_until_e(cursor):  # pylint: disable=too-many-return-statements
    """Like ``_itd._parse_encoding`` but terminated by ``E`` instead of EOF."""
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


def _patched_parse_name(cursor, is_nested=False):
    snap = _snapshot(cursor)
    try:
        return _orig_parse_name(cursor, is_nested)
    except NotImplementedError:
        if not _is_missing_production_at(cursor._raw, snap[0]):
            raise
        _restore(cursor, snap)
        node = _parse_missing_production(cursor)
        if node is None:
            return None
        return _apply_post_name_suffixes(cursor, node, is_nested)


_itd._parse_name = _patched_parse_name
