import asyncio
import collections.abc
import threading
import types

import immutables


__all__ = ('ContextVar', 'Context', 'Token', 'copy_context')


_NO_DEFAULT = object()


class ContextMeta(type(collections.abc.Mapping)):

    # contextvars.Context is not subclassable.

    def __new__(mcls, names, bases, dct):
        cls = super().__new__(mcls, names, bases, dct)
        if cls.__module__ != 'contextvars' or cls.__name__ != 'Context':
            raise TypeError("type 'Context' is not an acceptable base type")
        return cls


class Context(collections.abc.Mapping, metaclass=ContextMeta):

    def __init__(self):
        self._data = immutables.Map()
        self._prev_context = None

    def run(self, callable, *args, **kwargs):
        if self._prev_context is not None:
            raise RuntimeError(
                'cannot enter context: {} is already entered'.format(self))

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
            raise TypeError(
                "a ContextVar key was expected, got {!r}".format(var))
        return self._data[var]

    def __contains__(self, var):
        if not isinstance(var, ContextVar):
            raise TypeError(
                "a ContextVar key was expected, got {!r}".format(var))
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
        r = '<ContextVar name={!r}'.format(self.name)
        if self._default is not _NO_DEFAULT:
            r += ' default={!r}'.format(self._default)
        return r + ' at {:0x}>'.format(id(self))


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
        r += ' var={!r} at {:0x}>'.format(self._var, id(self))
        return r


def copy_context():
    return _get_context().copy()


def _get_context():
    state = _get_state()
    ctx = getattr(state, 'context', None)
    if ctx is None:
        ctx = Context()
        state.context = ctx
    return ctx


def _set_context(ctx):
    state = _get_state()
    state.context = ctx


def _get_state():
    loop = asyncio._get_running_loop()
    if loop is None:
        return _state
    task = asyncio.Task.current_task(loop=loop)
    return _state if task is None else task


_state = threading.local()


def create_task(loop, coro):
    task = loop._orig_create_task(coro)
    if task._source_traceback:
        del task._source_traceback[-1]
    task.context = copy_context()
    return task


def _patch_loop(loop):
    if loop and not hasattr(loop, '_orig_create_task'):
        loop._orig_create_task = loop.create_task
        loop.create_task = types.MethodType(create_task, loop)
    return loop


def get_event_loop():
    return _patch_loop(_get_event_loop())


def set_event_loop(loop):
    return _set_event_loop(_patch_loop(loop))


def new_event_loop():
    return _patch_loop(_new_event_loop())


_get_event_loop = asyncio.get_event_loop
_set_event_loop = asyncio.set_event_loop
_new_event_loop = asyncio.new_event_loop

asyncio.get_event_loop = asyncio.events.get_event_loop = get_event_loop
asyncio.set_event_loop = asyncio.events.set_event_loop = set_event_loop
asyncio.new_event_loop = asyncio.events.new_event_loop = new_event_loop
