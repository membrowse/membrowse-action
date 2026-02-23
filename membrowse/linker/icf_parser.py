#!/usr/bin/env python3

"""
icf_parser.py - IAR EWARM linker configuration file (.icf) parser.

Parses IAR ICF format linker scripts to extract memory region definitions
compatible with the MemBrowse analysis pipeline.

Key ICF constructs handled:
  define symbol NAME = VALUE;
  define memory mem with size = 4G;
  define region NAME = mem:[from ADDR to ADDR];
  define region NAME = mem:[from ADDR size SIZE];
  define region NAME = REGION_A | REGION_B;
  if (isdefinedsymbol(X)) { ... } else { ... }
  include "file.icf";

The output shape matches the GNU LD parser: Dict[str, MemoryRegion] where
MemoryRegion is the linker-local dataclass from parser.py.
"""

import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .base import LinkerScriptFormatParser, LinkerFormatDetector
from .parser import MemoryRegion, LinkerScriptError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ICFEvaluationError(LinkerScriptError):
    """Raised when an ICF expression cannot be evaluated."""


# ---------------------------------------------------------------------------
# Internal data structures
# ---------------------------------------------------------------------------

@dataclass
class _Span:  # pylint: disable=too-few-public-methods
    """A single contiguous address range [start, end] inclusive."""
    start: int
    end: int


@dataclass
class ICFRegionSpec:
    """Internal ICF region representation before output-dict conversion.

    A region may consist of multiple disjoint spans (from set union ops).
    The output contract collapses these to a bounding box with a warning.
    """
    name: str
    spans: List[_Span] = field(default_factory=list)
    explicitly_empty: bool = False

    @property
    def address(self) -> int:
        """Start address (minimum across all spans)."""
        return min(s.start for s in self.spans)

    @property
    def end_address(self) -> int:
        """End address inclusive (maximum across all spans)."""
        return max(s.end for s in self.spans)

    @property
    def limit_size(self) -> int:
        """Total size of the bounding box."""
        return self.end_address - self.address + 1

    def is_contiguous(self) -> bool:
        """Check if all spans form a single contiguous block."""
        if len(self.spans) <= 1:
            return True
        sorted_spans = sorted(self.spans, key=lambda s: s.start)
        return all(
            sorted_spans[i].end + 1 >= sorted_spans[i + 1].start
            for i in range(len(sorted_spans) - 1)
        )

    def to_memory_region(self) -> MemoryRegion:
        """Convert to linker-local MemoryRegion for the output pipeline."""
        if not self.is_contiguous() and len(self.spans) > 1:
            logger.warning(
                "ICF region '%s' is non-contiguous (union of disjoint spans). "
                "Collapsing to bounding box [0x%x, 0x%x].",
                self.name, self.address, self.end_address
            )
        return MemoryRegion(
            name=self.name,
            attributes="",
            address=self.address,
            limit_size=self.limit_size,
        )


# ---------------------------------------------------------------------------
# ICFSymbolTable
# ---------------------------------------------------------------------------

class ICFSymbolTable:
    """Stores and resolves IAR ICF symbol definitions.

    Handles ``define symbol NAME = VALUE;`` directives with multi-pass
    iterative resolution for forward references.
    """

    _SIZE_MULTIPLIERS = {
        "G": 1 << 30, "GB": 1 << 30,
        "M": 1 << 20, "MB": 1 << 20,
        "K": 1 << 10, "KB": 1 << 10,
    }

    def __init__(self) -> None:
        self._resolved: Dict[str, int] = {}
        self._unresolved: Dict[str, str] = {}
        self._regions: Dict[str, ICFRegionSpec] = {}

    def define_raw(self, name: str, raw_expr: str) -> None:
        """Record a raw symbol definition for later resolution."""
        self._unresolved[name] = raw_expr.strip()

    def seed(self, variables: Dict[str, Any]) -> None:
        """Pre-populate with user-supplied or architecture-default variables."""
        for k, v in variables.items():
            if isinstance(v, int):
                self._resolved[k] = v
            elif isinstance(v, str):
                self._unresolved[k] = v

    def register_region(self, spec: ICFRegionSpec) -> None:
        """Make a region available for start()/end()/size() built-ins."""
        self._regions[spec.name] = spec

    def resolve_all(self, max_passes: int = 15) -> None:
        """Iteratively resolve all symbols until convergence or stall."""
        for _ in range(max_passes):
            if not self._unresolved:
                break
            resolved_this_pass: Dict[str, int] = {}
            still_unresolved: Dict[str, str] = {}

            for name, raw in self._unresolved.items():
                try:
                    value = self.evaluate(raw)
                    resolved_this_pass[name] = value
                except (ValueError, ICFEvaluationError):
                    still_unresolved[name] = raw

            self._resolved.update(resolved_this_pass)
            if not resolved_this_pass:
                for name, raw in still_unresolved.items():
                    logger.debug(
                        "ICF symbol '%s' = '%s' could not be resolved",
                        name, raw
                    )
                break
            self._unresolved = still_unresolved

    def is_defined(self, name: str) -> bool:
        """Check if a symbol is defined (resolved or raw)."""
        return name in self._resolved or name in self._unresolved

    def evaluate(self, expr: str) -> int:
        """Evaluate an ICF expression to an integer."""
        expr = expr.strip()
        expr = self._expand_builtins(expr)
        expr = self._substitute_symbols(expr)
        expr = self._expand_size_suffixes(expr)
        return self._arithmetic_eval(expr)

    # ---- Built-in function expansion ----

    def _expand_builtins(self, expr: str) -> str:
        """Replace ICF built-in function calls with numeric values."""
        expr = re.sub(
            r'\bisdefinedsymbol\s*\(\s*([^)]+)\s*\)',
            lambda m: '1' if self.is_defined(m.group(1).strip()) else '0',
            expr
        )

        def _isempty_replacer(m):
            rname = m.group(1).strip()
            if rname in self._regions:
                return '0' if self._regions[rname].spans else '1'
            # Unknown region is treated as empty
            return '1'

        expr = re.sub(r'\bisempty\s*\(\s*([^)]+)\s*\)',
                       _isempty_replacer, expr)

        def _replace_region_fn(fn_name, attr):
            def replacer(m):
                rname = m.group(1).strip()
                if rname in self._regions and self._regions[rname].spans:
                    return str(getattr(self._regions[rname], attr))
                raise ICFEvaluationError(
                    f"{fn_name}(): unknown region '{rname}'")
            return replacer

        expr = re.sub(r'\bstart\s*\(\s*([^)]+)\s*\)',
                       _replace_region_fn('start', 'address'), expr)
        expr = re.sub(r'\bend\s*\(\s*([^)]+)\s*\)',
                       _replace_region_fn('end', 'end_address'), expr)
        expr = re.sub(r'\bsize\s*\(\s*([^)]+)\s*\)',
                       _replace_region_fn('size', 'limit_size'), expr)
        return expr

    # ---- Symbol substitution ----

    def _substitute_symbols(self, expr: str) -> str:
        """Replace known symbol names with their numeric values."""
        for sym in sorted(self._resolved, key=len, reverse=True):
            if sym in expr:
                pat = r'\b' + re.escape(sym) + r'\b'
                expr = re.sub(pat, str(self._resolved[sym]), expr)

        for sym in sorted(self._unresolved, key=len, reverse=True):
            if sym in expr:
                pat = r'\b' + re.escape(sym) + r'\b'
                if re.search(pat, expr):
                    raise ValueError(
                        f"Unresolved symbol '{sym}' in expression: {expr}")
        return expr

    # ---- Size suffix expansion ----

    def _expand_size_suffixes(self, expr: str) -> str:
        """Expand K/M/G/KB/MB/GB size suffixes to numeric values."""
        def replace_suffix(m):
            num = int(m.group(1))
            suffix = m.group(2).upper()
            return str(num * self._SIZE_MULTIPLIERS[suffix])

        return re.sub(
            r'(\d+)\s*(GB?|MB?|KB?)\b',
            replace_suffix,
            expr,
            flags=re.IGNORECASE
        )

    # ---- Arithmetic evaluator ----

    def _arithmetic_eval(self, expr: str) -> int:  # pylint: disable=too-many-locals,too-many-statements
        """Safe recursive-descent arithmetic evaluator.

        Operator precedence (lowest to highest):
          ternary     ? :
          logical OR  ||
          logical AND &&
          comparison  == != > >= < <=
          bitwise OR  |
          bitwise AND &
          shift       << >>
          add/sub     + -
          mul/div     * /
          unary       ~ - + !
          atom        literal | (expr)
        """
        expr = expr.replace(" ", "").replace("\t", "")

        # Expand hex literals to decimal
        expr = re.sub(
            r'0[xX]([0-9a-fA-F]+)',
            lambda m: str(int(m.group(1), 16)),
            expr
        )

        if not expr:
            raise ICFEvaluationError("Empty expression")

        # Allow only safe characters (includes ? and : for ternary)
        if not re.match(r'^[0-9+\-*/&|~<>=!()?:]+$', expr):
            raise ICFEvaluationError(f"Unsafe characters in expression: {expr}")

        idx = [0]

        def peek():
            return expr[idx[0]] if idx[0] < len(expr) else None

        def peek2():
            return expr[idx[0]:idx[0] + 2] if idx[0] + 1 < len(expr) else ''

        def consume(n=1):
            idx[0] += n

        def parse_atom():
            ch = peek()
            if ch is None:
                raise ICFEvaluationError("Unexpected end of expression")
            if ch == '(':
                consume()
                val = parse_ternary()
                if peek() != ')':
                    raise ICFEvaluationError("Missing closing parenthesis")
                consume()
                return val
            if ch == '!':
                consume()
                return 0 if parse_atom() else 1
            if ch == '~':
                consume()
                return ~parse_atom()
            if ch == '-':
                consume()
                return -parse_atom()
            if ch == '+':
                consume()
                return parse_atom()
            start = idx[0]
            while idx[0] < len(expr) and expr[idx[0]].isdigit():
                idx[0] += 1
            if idx[0] == start:
                raise ICFEvaluationError(
                    f"Expected number at position {idx[0]} in '{expr}'")
            return int(expr[start:idx[0]])

        def parse_muldiv():
            left = parse_atom()
            while peek() in ('*', '/'):
                op = peek()
                consume()
                right = parse_atom()
                if op == '*':
                    left *= right
                else:
                    if right == 0:
                        raise ICFEvaluationError("Division by zero")
                    left //= right
            return left

        def parse_addsub():
            left = parse_muldiv()
            while peek() in ('+', '-'):
                op = peek()
                consume()
                right = parse_muldiv()
                left = left + right if op == '+' else left - right
            return left

        def parse_shift():
            left = parse_addsub()
            while idx[0] < len(expr) - 1 and expr[idx[0]:idx[0] + 2] in ('<<', '>>'):
                op = expr[idx[0]:idx[0] + 2]
                consume(2)
                right = parse_addsub()
                left = left << right if op == '<<' else left >> right
            return left

        def parse_bitand():
            left = parse_shift()
            while peek() == '&' and peek2() != '&&':
                consume()
                left &= parse_shift()
            return left

        def parse_bitor():
            left = parse_bitand()
            while peek() == '|' and peek2() != '||':
                consume()
                left |= parse_bitand()
            return left

        def parse_comparison():
            left = parse_bitor()
            while idx[0] < len(expr):
                two = peek2()
                if two == '==':
                    consume(2)
                    left = 1 if left == parse_bitor() else 0
                    continue
                if two == '!=':
                    consume(2)
                    left = 1 if left != parse_bitor() else 0
                    continue
                if two == '>=':
                    consume(2)
                    left = 1 if left >= parse_bitor() else 0
                    continue
                if two == '<=':
                    consume(2)
                    left = 1 if left <= parse_bitor() else 0
                    continue
                ch = peek()
                if ch == '>' and peek2() not in ('>>', '>='):
                    consume()
                    left = 1 if left > parse_bitor() else 0
                    continue
                if ch == '<' and peek2() not in ('<<', '<='):
                    consume()
                    left = 1 if left < parse_bitor() else 0
                    continue
                break
            return left

        def parse_logical_and():
            left = parse_comparison()
            while peek2() == '&&':
                consume(2)
                right = parse_comparison()
                left = 1 if (left and right) else 0
            return left

        def parse_logical_or():
            left = parse_logical_and()
            while peek2() == '||':
                consume(2)
                right = parse_logical_and()
                left = 1 if (left or right) else 0
            return left

        def parse_ternary():
            cond = parse_logical_or()
            if peek() == '?':
                consume()
                true_val = parse_ternary()
                if peek() != ':':
                    raise ICFEvaluationError(
                        "Expected ':' in ternary expression")
                consume()
                false_val = parse_ternary()
                return true_val if cond else false_val
            return cond

        result = parse_ternary()
        if idx[0] < len(expr):
            raise ICFEvaluationError(
                f"Unexpected character at position {idx[0]}: "
                f"'{expr[idx[0]]}' in '{expr}'")
        return result


# ---------------------------------------------------------------------------
# ICFContentPreprocessor
# ---------------------------------------------------------------------------

class ICFContentPreprocessor:  # pylint: disable=too-few-public-methods
    """Strips comments and inlines include directives."""

    def __init__(self, max_depth: int = 10) -> None:
        self._max_depth = max_depth
        self._visited: Set[Path] = set()

    def preprocess(self, content: str, current_path: Path) -> str:
        """Strip comments and inline includes for an ICF file."""
        self._visited.add(current_path.resolve())
        content = self._strip_comments(content)
        content = self._inline_includes(content, current_path.parent, depth=0)
        return content

    @staticmethod
    def _strip_comments(content: str) -> str:
        """Remove C-style block and line comments."""
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        content = re.sub(r'//[^\n]*', '', content)
        return content

    def _inline_includes(
            self, content: str, current_dir: Path, depth: int) -> str:
        """Recursively replace include directives with file contents."""
        if depth > self._max_depth:
            logger.warning("ICF include depth exceeded %d; stopping.",
                           self._max_depth)
            return content

        def replace_include(m):
            include_path = (current_dir / m.group(1)).resolve()
            if include_path in self._visited:
                return ''
            self._visited.add(include_path)
            try:
                included = include_path.read_text(encoding='utf-8')
                included = self._strip_comments(included)
                return self._inline_includes(
                    included, include_path.parent, depth + 1)
            except OSError as exc:
                logger.warning("Cannot read ICF include '%s': %s",
                               include_path, exc)
                return ''

        return re.sub(
            r'\binclude\s+"([^"]+)"\s*;?', replace_include, content)


# ---------------------------------------------------------------------------
# ICFConditionalEvaluator
# ---------------------------------------------------------------------------

class ICFConditionalEvaluator:  # pylint: disable=too-few-public-methods
    """Evaluates if/else/endif blocks using brace-depth matching.

    ICF conditionals use curly braces:
        if (condition) { ... } else { ... }
    """

    def __init__(self, symbols: ICFSymbolTable) -> None:
        self._symbols = symbols

    def evaluate_conditionals(self, content: str) -> str:
        """Process if/else blocks from innermost out until none remain."""
        max_passes = 50
        for _ in range(max_passes):
            new_content = self._process_one_pass(content)
            if new_content == content:
                break
            content = new_content
        return content

    def _process_one_pass(self, content: str) -> str:  # pylint: disable=too-many-locals
        """Find and replace the first (outermost-leftmost) if block."""
        # Find 'if (' then use paren-depth matching to extract the full condition
        # (handles nested parens like isdefinedsymbol(...))
        match = re.search(r'\bif\s*\(', content)
        if not match:
            return content

        # Extract condition using balanced parentheses
        paren_start = match.end() - 1  # position of '('
        cond_end = self._find_matching_paren(content, paren_start)
        if cond_end == -1:
            return content

        cond_str = content[paren_start + 1:cond_end].strip()

        # Find the '{' after the condition's closing ')'
        after_cond = content[cond_end + 1:].lstrip()
        if not after_cond.startswith('{'):
            return content
        brace_start = content.index('{', cond_end + 1)
        true_end = self._find_matching_brace(content, brace_start)
        if true_end == -1:
            return content

        true_body = content[brace_start + 1:true_end]

        # Check for else branch (handles both 'else {' and 'else if (...) {')
        else_body = ""
        after_end = true_end + 1
        rest = content[true_end + 1:]

        else_brace_match = re.match(r'\s*else\s*\{', rest)
        else_if_match = re.match(r'\s*else\s+if\b', rest)

        if else_brace_match:
            # Standard 'else { ... }'
            else_brace_start = true_end + 1 + else_brace_match.end() - 1
            else_end = self._find_matching_brace(content, else_brace_start)
            if else_end != -1:
                else_body = content[else_brace_start + 1:else_end]
                after_end = else_end + 1
        elif else_if_match:
            # 'else if (...)' — treat the nested 'if (...) { ... }' chain
            # as the else body so it gets processed in subsequent passes
            # Find 'else' keyword and skip it to get the 'if ...' portion
            else_keyword_end = true_end + 1 + re.match(
                r'\s*else\s+', rest).end()
            # Find the actual end of the nested if chain so trailing
            # content is preserved regardless of which branch is taken
            chain_end = self._find_if_chain_end(content, else_keyword_end)
            else_body = content[else_keyword_end:chain_end]
            after_end = chain_end

        try:
            cond_result = bool(self._symbols.evaluate(cond_str))
        except (ICFEvaluationError, ValueError) as exc:
            logger.warning(
                "ICF: cannot evaluate condition '%s': %s. "
                "Defaulting to false branch.", cond_str, exc)
            cond_result = False

        chosen = true_body if cond_result else else_body
        return content[:match.start()] + chosen + content[after_end:]

    @staticmethod
    def _find_matching(content: str, open_pos: int,
                       open_ch: str, close_ch: str) -> int:
        """Return position of the matching close character, or -1."""
        depth = 1
        pos = open_pos + 1
        while pos < len(content) and depth > 0:
            if content[pos] == open_ch:
                depth += 1
            elif content[pos] == close_ch:
                depth -= 1
            pos += 1
        return pos - 1 if depth == 0 else -1

    @classmethod
    def _find_matching_paren(cls, content: str, open_pos: int) -> int:
        """Return position of paren matching '(' at open_pos, or -1."""
        return cls._find_matching(content, open_pos, '(', ')')

    @classmethod
    def _find_matching_brace(cls, content: str, open_pos: int) -> int:
        """Return position of brace matching '{' at open_pos, or -1."""
        return cls._find_matching(content, open_pos, '{', '}')

    @classmethod
    def _find_if_chain_end(cls, content: str, pos: int) -> int:
        """Find the end of an if/else-if/else chain starting at pos.

        pos should point to the 'i' in 'if'. Returns the position just
        past the last closing brace of the chain.
        """
        while True:
            if_match = re.match(r'if\s*\(', content[pos:])
            if not if_match:
                return pos

            paren_start = pos + if_match.end() - 1
            paren_end = cls._find_matching(content, paren_start, '(', ')')
            if paren_end == -1:
                return len(content)

            after_paren = content[paren_end + 1:].lstrip()
            if not after_paren.startswith('{'):
                return paren_end + 1
            brace_start = content.index('{', paren_end + 1)
            brace_end = cls._find_matching(content, brace_start, '{', '}')
            if brace_end == -1:
                return len(content)

            rest_after = content[brace_end + 1:]
            else_brace = re.match(r'\s*else\s*\{', rest_after)
            else_if = re.match(r'\s*else\s+if\b', rest_after)

            if else_brace:
                eb_start = brace_end + 1 + else_brace.end() - 1
                eb_end = cls._find_matching(content, eb_start, '{', '}')
                return len(content) if eb_end == -1 else eb_end + 1
            if else_if:
                skip = re.match(r'\s*else\s+', rest_after).end()
                pos = brace_end + 1 + skip
                continue
            return brace_end + 1


# ---------------------------------------------------------------------------
# IARLinkerScriptParser
# ---------------------------------------------------------------------------

class IARLinkerScriptParser(LinkerScriptFormatParser):
    """Parser for IAR EWARM linker configuration files (.icf).

    Implements LinkerScriptFormatParser. Called by LinkerScriptParser
    when content-based detection identifies an ICF file.
    """

    def __init__(self, user_variables: Optional[Dict[str, Any]] = None) -> None:
        self._user_variables = user_variables or {}

    @staticmethod
    def detect(content: str) -> bool:
        """Return True if content looks like an IAR ICF file."""
        return LinkerFormatDetector.is_icf(content)

    def parse(self, script_path: str) -> Dict[str, MemoryRegion]:
        """Parse an ICF file and return MemoryRegion objects keyed by name.

        Pipeline:
          1. Preprocess (strip comments, inline includes)
          2. Extract ``define symbol`` directives
          3. Resolve symbols to integers (multi-pass)
          4. Evaluate if/else conditionals
          5. Re-extract symbols from surviving branches
          6. Parse ``define region`` directives
          7. Resolve region set operations
          8. Convert ICFRegionSpec -> MemoryRegion
        """
        path = Path(script_path).resolve()
        content = path.read_text(encoding='utf-8')

        # Stage 1: Preprocess
        preprocessor = ICFContentPreprocessor()
        content = preprocessor.preprocess(content, path)

        # Stage 2-3: Build and resolve symbol table
        symbols = ICFSymbolTable()
        symbols.seed(self._user_variables)
        self._extract_symbols(content, symbols)
        symbols.resolve_all()

        # Stage 4: Evaluate conditionals
        cond_eval = ICFConditionalEvaluator(symbols)
        content = cond_eval.evaluate_conditionals(content)

        # Stage 5: Re-extract symbols from surviving conditional branches
        self._extract_symbols(content, symbols)
        symbols.resolve_all()

        # Stage 6: Parse define region directives
        region_specs = self._parse_region_specs(content, symbols)

        # Register all regions (including empty) for built-ins
        for spec in region_specs.values():
            symbols.register_region(spec)

        # Stage 7: Resolve set operations for regions with empty spans
        self._resolve_set_operations(content, region_specs, symbols)

        # Stage 8: Convert to MemoryRegion output
        result: Dict[str, MemoryRegion] = {}
        for name, spec in region_specs.items():
            if not spec.spans:
                if not spec.explicitly_empty:
                    logger.warning(
                        "ICF region '%s' has no spans; skipping.", name)
                continue
            result[name] = spec.to_memory_region()

        if not result and region_specs:
            # Don't count explicitly-empty regions as failures
            non_empty_specs = [
                k for k, v in region_specs.items()
                if not v.explicitly_empty
            ]
            if non_empty_specs:
                raise LinkerScriptError(
                    f"ICF parser could not resolve any memory regions "
                    f"from {path.name}: {', '.join(sorted(non_empty_specs))}")

        logger.info("ICF parser extracted %d memory regions from %s",
                     len(result), path.name)
        return result

    # ------------------------------------------------------------------
    # Symbol extraction
    # ------------------------------------------------------------------

    _SYMBOL_PATTERN = re.compile(
        r'\bdefine\s+(?:exported\s+)?symbol\s+(\w+)\s*=\s*([^;]+);',
        re.IGNORECASE
    )

    @classmethod
    def _extract_symbols(cls, content: str, symbols: ICFSymbolTable) -> None:
        """Extract all ``define symbol NAME = EXPR;`` statements."""
        for m in cls._SYMBOL_PATTERN.finditer(content):
            symbols.define_raw(m.group(1), m.group(2))

    # ------------------------------------------------------------------
    # Region parsing
    # ------------------------------------------------------------------

    _REGION_DEF_PATTERN = re.compile(
        r'\bdefine\s+region\s+(\w+)\s*=\s*([^;]+);',
        re.IGNORECASE
    )

    _MEM_SPAN_PATTERN = re.compile(
        r'(?:\w+\s*:)?\s*\[\s*from\s+(.+?)'
        r'(?:\s+to\s+(.+?)|\s+size\s+(.+?))'
        r'\s*\]',
        re.IGNORECASE
    )

    # Matches `[]` (empty region literal, possibly with whitespace)
    _EMPTY_REGION_PATTERN = re.compile(r'^\s*\[\s*\]\s*$')

    def _parse_region_specs(
            self, content: str, symbols: ICFSymbolTable
    ) -> Dict[str, ICFRegionSpec]:
        """Parse all ``define region`` directives."""
        specs: Dict[str, ICFRegionSpec] = {}

        for m in self._REGION_DEF_PATTERN.finditer(content):
            name = m.group(1)
            rhs = m.group(2).strip()
            spec = ICFRegionSpec(name=name)

            # Handle explicit empty region: `define region X = [];`
            if self._EMPTY_REGION_PATTERN.match(rhs):
                spec.explicitly_empty = True
                specs[name] = spec
                continue

            # Find all mem:[...] spans in the RHS (handles union inline)
            for span_match in self._MEM_SPAN_PATTERN.finditer(rhs):
                try:
                    span = self._parse_mem_span(span_match, symbols)
                    spec.spans.append(span)
                except (ICFEvaluationError, ValueError) as exc:
                    logger.debug("Cannot parse span in region '%s': %s",
                                 name, exc)

            specs[name] = spec

        return specs

    @staticmethod
    def _parse_mem_span(m: re.Match, symbols: ICFSymbolTable) -> _Span:
        """Parse a mem:[from X to Y] or mem:[from X size Y] match."""
        from_expr = m.group(1).strip()
        to_expr = m.group(2)
        size_expr = m.group(3)

        start_addr = symbols.evaluate(from_expr)

        if to_expr is not None:
            end_addr = symbols.evaluate(to_expr.strip())
        else:
            region_size = symbols.evaluate(size_expr.strip())
            end_addr = start_addr + region_size - 1

        if end_addr < start_addr:
            raise ICFEvaluationError(
                f"Region end (0x{end_addr:x}) < start (0x{start_addr:x})")

        return _Span(start=start_addr, end=end_addr)

    # ------------------------------------------------------------------
    # Region set operations
    # ------------------------------------------------------------------

    def _resolve_set_operations(
            self,
            content: str,
            specs: Dict[str, ICFRegionSpec],
            _symbols: ICFSymbolTable,
    ) -> None:
        """Resolve set-operation region definitions (regions with empty spans)."""
        for m in self._REGION_DEF_PATTERN.finditer(content):
            name = m.group(1)
            rhs = m.group(2).strip()
            spec = specs.get(name)
            if spec is None or spec.spans:
                continue
            # Skip regions explicitly defined as empty (`= []`)
            if spec.explicitly_empty:
                continue

            try:
                result_spans = self._eval_region_set_expr(rhs, specs)
                spec.spans.extend(result_spans)
            except ICFEvaluationError as exc:
                logger.warning(
                    "Cannot resolve set operation for region '%s': %s",
                    name, exc)

    def _eval_region_set_expr(
            self,
            expr: str,
            known_specs: Dict[str, ICFRegionSpec],
    ) -> List[_Span]:
        """Evaluate a region set expression recursively.

        Operators: | and + (union), - (difference), & (intersection).
        """
        expr = expr.strip()

        # Try splitting on union operators (lowest precedence for regions)
        for op_char in ('|', '+'):
            parts = self._split_set_op(expr, op_char)
            if parts:
                left = self._eval_region_set_expr(parts[0], known_specs)
                right = self._eval_region_set_expr(parts[1], known_specs)
                return left + right  # union = concatenate spans

        # Try difference
        parts = self._split_set_op(expr, '-')
        if parts:
            left = self._eval_region_set_expr(parts[0], known_specs)
            right = self._eval_region_set_expr(parts[1], known_specs)
            return self._difference_spans(left, right)

        # Try intersection
        parts = self._split_set_op(expr, '&')
        if parts:
            left = self._eval_region_set_expr(parts[0], known_specs)
            right = self._eval_region_set_expr(parts[1], known_specs)
            return self._intersect_spans(left, right)

        # Leaf: a region name reference (or empty region literal [])
        region_name = expr.strip()
        if region_name == '[]' or re.match(r'^\[\s*\]$', region_name):
            return []  # empty region literal
        if region_name in known_specs:
            return list(known_specs[region_name].spans)

        raise ICFEvaluationError(
            f"Unknown region in set expression: '{region_name}'")

    @staticmethod
    def _split_set_op(
            expr: str, op: str) -> Optional[Tuple[str, str]]:
        """Split expr on the rightmost occurrence of op outside brackets."""
        depth = 0
        for i in range(len(expr) - 1, -1, -1):
            ch = expr[i]
            if ch == ']':
                depth += 1
            elif ch == '[':
                depth -= 1
            elif ch == op and depth == 0:
                left = expr[:i].strip()
                right = expr[i + 1:].strip()
                if left and right:
                    return left, right
        return None

    @staticmethod
    def _difference_spans(
            a: List[_Span], b: List[_Span]) -> List[_Span]:
        """Remove b spans from a spans (punch holes)."""
        result = list(a)
        for excl in b:
            new_result = []
            for span in result:
                if span.start < excl.start:
                    new_result.append(
                        _Span(span.start, min(span.end, excl.start - 1)))
                if span.end > excl.end:
                    new_result.append(
                        _Span(max(span.start, excl.end + 1), span.end))
            result = new_result
        return result

    @staticmethod
    def _intersect_spans(
            a: List[_Span], b: List[_Span]) -> List[_Span]:
        """Return spans present in both a and b."""
        result = []
        for sa in a:
            for sb in b:
                lo = max(sa.start, sb.start)
                hi = min(sa.end, sb.end)
                if lo <= hi:
                    result.append(_Span(lo, hi))
        return result
