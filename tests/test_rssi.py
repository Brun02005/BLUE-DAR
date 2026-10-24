from bluedar.proximity.rssi import RssiTracker


def feed(tracker, values, start=0.0, step=1.0):
    for i, v in enumerate(values):
        tracker.add(start + i * step, v)


def test_category_hysteresis_avoids_flapping():
    t = RssiTracker()
    feed(t, [-55] * 10)
    assert t.state().category == "fuerte"
    feed(t, [-61] * 20, start=10)  # 1 dB debajo del umbral: dentro de la histéresis
    assert t.state().category == "fuerte"
    feed(t, [-70] * 20, start=30)
    assert t.state().category == "media"
    feed(t, [-58] * 20, start=50)  # sube 2 dB por encima del umbral: no alcanza
    assert t.state().category == "media"
    feed(t, [-80] * 20, start=70)
    assert t.state().category == "débil"


def test_median_filters_outliers():
    t = RssiTracker()
    feed(t, [-70, -70, -40, -70, -70], step=0.5)
    assert t.state().smoothed < -65


def test_trend_detects_approach_and_stability():
    t = RssiTracker()
    feed(t, [-85 + i for i in range(25)])
    assert t.state().trend == "acercándose"
    s = RssiTracker()
    feed(s, [-70, -72, -69, -71] * 6)
    assert s.state().trend == "estable"


def test_trend_needs_enough_data():
    t = RssiTracker()
    feed(t, [-70, -60])
    assert t.state().trend is None
