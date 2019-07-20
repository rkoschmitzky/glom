"""
Contains code associated with implementing "match" mode

match mode tends to build expression trees by conjoining
together matches with And / &, Or / |

example use cases:

filter list on condition (e.g. >= 10)
[Coalesce(Match(int & (M >= 10)), default=SKIP)]

ensure that dictionary values are all strings
Match({DEFAULT: str})

3 syntaxes for combining expressions:

(int) & (M > 0)
And(int, M > 0)
And & int & (M > 0)

"""
from boltons.typeutils import make_sentinel

import weakref

from .core import GlomError, glom


class GlomMatchError(GlomError): pass
class GlomTypeMatchError(GlomError, TypeError): pass


class Match(object):
    """
    switch to "match" mode
    """
    def __init__(self, spec):
        self.spec = spec

    def glomit(self, target, scope):
        scope[glom] = _glom_match
        return scope[glom](target, self.spec, scope)


DEFAULT = make_sentinel("DEFAULT")
DEFAULT.__doc__ = """
DEFAULT is used to represent keys that are not otherwise matched
in a dict in match mode
"""

class _Bool(object):
    """
    abstract class for binary operations
    """
    def __and__(self, other):
        return And(self, other)

    def __or__(self, other):
        return Or(self, other)


class _AndMeta(type):
    def __and__(self, other):
        return And(other)


#python 2/3 meta-class compatibility hack
class And(_AndMeta('_AndBool', (_Bool,), {})):
    def __init__(self, *children):
        self.children = children

    def glomit(self, target, scope):
        # all children must match without exception
        for child in children:
            scope[glom](target, child, scope)


class _OrMeta(type):
    def __or__(self, other):
        return Or(other)


class Or(_OrMeta('_OrBool', (_Bool,), {})):
    def __init__(self, *children):
        self.children = children

    def glomit(self, target, scope):
        for child in children:
            try:  # one child must match without exception
                scope[glom](target, child, scope)
                return
            except GlomMatchError:
                pass


class MType(object):
    """
    Similar to T, but for matching
    """
    __slots__ = ('__weakref__',)

    def __eq__(self, other):
        return _m_child(self, '=', other)

    def __gt__(self, other):
        return _m_child(self, '>', other)

    def __lt__(self, other):
        return _m_child(self, '<', other)

    # TODO: straightforward to extend this to all comparisons



_M_EXPRS = weakref.WeakKeyDictionary()

M = MType()

_M_EXPRS[M] = (M,)


def _precedence(match):
    """
    in a dict spec, target-keys may match many
    spec-keys (e.g. 1 will match int, M > 0, and 1);
    therefore we need a precedence for which order to try
    keys in; higher = later
    """
    if type(match) in (list, tuple, set, frozenset, dict):
        return 4
    if isinstance(match, type):
        return 3
    if hasattr(match, "glomit"):
        return 2
    if callable(match):
        return 1
    return 0  # == match


def _handle_dict(target, spec, scope):
    if not isinstance(target, dict):
        raise GlomTypeMatchError(type(target), dict)
    spec_keys = sorted(spec, key=_precedence)
    for key, val in target.items():
        for spec_key in spec_keys:
            try:
                _glom_match(key, spec_key, scope)
            except GlomMatchError:
                pass
            else:
                _glom_match(val, spec[spec_key], scope)
                break
        else:
            raise GlomMatchError("key {!r} didn't match any of {!r}".format(key, spec_keys))


def _glom_match(target, spec, scope):
    scope = scope.new_child()
    scope[T] = target
    scope[Spec] = spec

    if callable(getattr(spec, 'glomit', None)):
        return spec.glomit(target, scope)
    elif isinstance(spec, type):
        if not isinstance(target, spec):
            raise GlomTypeMatchError(type(target), spec)
    elif isinstance(spec, dict):
        return _handle_dict(target, spec, scope)
    elif isinstance(spec, list):
        if not isinstance(target, list):
            raise GlomTypeMatchError(type(target), list)
        for item in target:
            last_error = None
            for child in spec:
                try:
                    _glom_match(item, child, scope)
                    break
                except GlomMatchError as e:
                    last_error = e
            else:
                if target and not spec:
                    raise GlomMatchError("{!r} does not match empty list".format(target))
                raise e
    # ...
    elif isinstance(spec, tuple):
        return _handle_tuple(target, spec, scope)
    elif callable(spec):
        return spec(target)

    raise TypeError('expected spec to be dict, list, tuple, callable, string,'
                    ' or other Spec-like type, not: %r' % (spec,))

