from claimledger.runtime_metrics import peak_rss_bytes


def test_peak_rss_bytes_is_a_nonnegative_integer():
    value = peak_rss_bytes()

    assert isinstance(value, int)
    assert value >= 0
