from textkit.slug import slugify


def test_lowercases_and_hyphenates():
    assert slugify("Hello World") == "hello-world"


def test_strips_surrounding_spaces():
    assert slugify("  Top News  ") == "top-news"
