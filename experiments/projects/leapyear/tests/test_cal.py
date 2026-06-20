from cal.leap import is_leap


def test_regular_leap():
    assert is_leap(2020) is True


def test_century_not_leap():
    assert is_leap(1900) is False


def test_400_is_leap():
    assert is_leap(2000) is True
