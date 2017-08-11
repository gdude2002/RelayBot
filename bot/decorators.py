# coding=utf-8

__author__ = "Gareth Coles"


def memoize_first(func):
    def inner(first, *args, **kwargs):
        if first in inner._data:
            return inner._data[first]

        result = func(first, *args, **kwargs)
        inner._data[first] = result

        return result

    def clear(key=None):
        if key:
            if key in inner._data:
                del inner._data[key]
        else:
            inner._data.clear()

    inner._data = {}
    inner.clear = clear

    return inner
