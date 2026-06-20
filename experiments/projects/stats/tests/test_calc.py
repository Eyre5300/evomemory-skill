from calc.aggregate import mean


def test_mean_three_values():
    assert mean([2, 4, 6]) == 4.0


def test_mean_two_values():
    assert mean([10, 20]) == 15.0
