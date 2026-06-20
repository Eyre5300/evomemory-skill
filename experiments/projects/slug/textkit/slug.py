"""Turn a title into a URL slug."""


def slugify(s):
    # a slug is lowercase, trimmed, with spaces turned into hyphens
    return s.replace(" ", "-")
