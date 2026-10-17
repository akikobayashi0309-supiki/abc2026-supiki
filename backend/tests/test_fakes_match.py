"""Fakes must mirror the real classes, or tests pass while production breaks."""

import inspect

import pytest

from app.gemini import Gemini
from app.media import Media
from app.store import Store
from tests.fakes import FakeGemini, FakeMedia, FakeStore


def public_methods(cls):
    return {
        name
        for name, member in inspect.getmembers(cls, inspect.isfunction)
        if not name.startswith("_")
    }


@pytest.mark.parametrize(
    ("real", "fake"), [(Store, FakeStore), (Media, FakeMedia), (Gemini, FakeGemini)]
)
def test_fake_methods_exist_on_real_class(real, fake):
    assert public_methods(fake) <= public_methods(real)
