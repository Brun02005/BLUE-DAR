from bluedar.proximity.distance import estimate_distance


def test_interval_brackets_and_widens_with_distance():
    near = estimate_distance(-55)   # señal fuerte, cerca
    far = estimate_distance(-90)    # señal débil, lejos / a través de paredes
    assert near.low_m <= near.nominal_m <= near.high_m
    assert far.nominal_m > near.nominal_m
    # El intervalo absoluto se ensancha con la distancia.
    assert (far.high_m - far.low_m) > (near.high_m - near.low_m)


def test_uncalibrated_is_flagged_and_wide():
    e = estimate_distance(-80)
    assert not e.calibrated and "sin calibrar" in e.text()
    assert e.high_m / e.low_m >= 3  # sin calibrar, el rango abarca un factor grande


def test_very_strong_signal_reads_as_very_near():
    assert "muy cerca" in estimate_distance(-35).text()


def test_very_weak_signal_is_marked_uncertain():
    e = estimate_distance(-98)
    assert e.uncertain and e.text().startswith(">")


def test_calibration_narrows_the_interval():
    generic = estimate_distance(-70)
    calibrated = estimate_distance(-70, ref_dbm=-62, n=2.6, calibrated=True)
    assert (calibrated.high_m - calibrated.low_m) < (generic.high_m - generic.low_m)
    assert "sin calibrar" not in calibrated.text()


def test_spread_widens_interval():
    tight = estimate_distance(-70, spread_db=1)
    noisy = estimate_distance(-70, spread_db=20)
    assert (noisy.high_m - noisy.low_m) > (tight.high_m - tight.low_m)
