import collections.abc
import threading


__all__ = ('ContextVar', 'Context', 'Token', 'copy_context')


_NO_DEFAULT = object()


class _ContextData:

    def __init__(self):
        self._mapping = dict()

    def __getitem__(self, key):
        return self._mapping[key]

    def __contains__(self, key):
        return key in self._mapping

    def __len__(self):
        return len(self._mapping)

    def __iter__(self):
        return iter(self._mapping)

    def set(self, key, value):
        copy = _ContextData()
        copy._mapping = self._mapping.copy()
        copy._mapping[key] = value
        return copy

    def delete(self, key):
        copy = _ContextData()
        copy._mapping = self._mapping.copy()
        del copy._mapping[key]
        return copy


class ContextMeta(type(collections.abc.Mapping)):

    # contextvars.Context is not subclassable.

    def __new__(mcls, names, bases, dct):
        cls = super().__new__(mcls, names, bases, dct)
        if cls.__module__ != 'contextvars' or cls.__name__ != 'Context':
            raise TypeError("type 'Context' is not an acceptable base type")
        return cls


class Context(collections.abc.Mapping, metaclass=ContextMeta):

    def __init__(self):
        self._data = _ContextData()
        self._prev_context = None

    def run(self, callable, *args, **kwargs):
        if self._prev_context is not None:
            raise RuntimeError(
                f'cannot enter context: {self} is already entered')

        self._prev_context = _get_context()
        try:
            _set_context(self)
            return callable(*args, **kwargs)
        finally:
            _set_context(self._prev_context)
            self._prev_context = None

    def copy(self):
        new = Context()
        new._data = self._data
        return new

    def __getitem__(self, var):
        if not isinstance(var, ContextVar):
            raise TypeError(f"a ContextVar key was expected, got {var!r}")
        return self._data[var]

    def __contains__(self, var):
        if not isinstance(var, ContextVar):
            raise TypeError(f"a ContextVar key was expected, got {var!r}")
        return var in self._data

    def __len__(self):
        return len(self._data)

    def __iter__(self):
        return iter(self._data)


class ContextVarMeta(type):

    # contextvars.ContextVar is not subclassable.

    def __new__(mcls, names, bases, dct):
        cls = super().__new__(mcls, names, bases, dct)
        if cls.__module__ != 'contextvars' or cls.__name__ != 'ContextVar':
            raise TypeError("type 'ContextVar' is not an acceptable base type")
        return cls

    def __getitem__(cls, name):
        return


class ContextVar(metaclass=ContextVarMeta):

    def __init__(self, name, *, default=_NO_DEFAULT):
        if not isinstance(name, str):
            raise TypeError("context variable name must be a str")
        self._name = name
        self._default = default

    @property
    def name(self):
        return self._name

    def get(self, default=_NO_DEFAULT):
        ctx = _get_context()
        try:
            return ctx[self]
        except KeyError:
            pass

        if default is not _NO_DEFAULT:
            return default

        if self._default is not _NO_DEFAULT:
            return self._default

        raise LookupError

    def set(self, value):
        ctx = _get_context()
        data = ctx._data
        try:
            old_value = data[self]
        except KeyError:
            old_value = Token.MISSING

        updated_data = data.set(self, value)
        ctx._data = updated_data
        return Token(ctx, self, old_value)

    def reset(self, token):
        if token._used:
            raise RuntimeError("Token has already been used once")

        if token._var is not self:
            raise ValueError(
                "Token was created by a different ContextVar")

        if token._context is not _get_context():
            raise ValueError(
                "Token was created in a different Context")

        ctx = token._context
        if token._old_value is Token.MISSING:
            ctx._data = ctx._data.delete(token._var)
        else:
            ctx._data = ctx._data.set(token._var, token._old_value)

        token._used = True

    def __repr__(self):
        r = f"<ContextVar name={self.name!r}"
        if self._default is not _NO_DEFAULT:
            r += f' default={self._default!r}'
        return r + f" at {id(self):0x}>"


class TokenMeta(type):

    # contextvars.Token is not subclassable.

    def __new__(mcls, names, bases, dct):
        cls = super().__new__(mcls, names, bases, dct)
        if cls.__module__ != 'contextvars' or cls.__name__ != 'Token':
            raise TypeError("type 'Token' is not an acceptable base type")
        return cls


class Token(metaclass=TokenMeta):

    MISSING = object()

    def __init__(self, context, var, old_value):
        self._context = context
        self._var = var
        self._old_value = old_value
        self._used = False

    @property
    def var(self):
        return self._var

    @property
    def old_value(self):
        return self._old_value

    def __repr__(self):
        r = '<Token '
        if self._used:
            r += ' used'
        r += f' var={self._var!r} at {id(self):0x}>'
        return r


def copy_context():
    return _get_context().copy()


def _get_context():
    ctx = getattr(_state, 'context', None)
    if ctx is None:
        ctx = Context()
        _state.context = ctx
    return ctx


def _set_context(ctx):
    _state.context = ctx


_state = threading.local()