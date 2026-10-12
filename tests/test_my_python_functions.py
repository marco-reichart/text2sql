"""Unit tests."""

from my_python_functions import myfunc


def test_myfunc():
    """Add a docstring to your functions."""
    res = myfunc(2)
    exp = 4.0
    assert res == exp
