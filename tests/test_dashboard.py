from pathlib import Path
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).parents[1] / "dashboard" / "app.py")


def test_dashboard_starts_and_steps():
    at = AppTest.from_file(APP, default_timeout=120).run()
    assert not at.exception
    at.button[0].click().run()  # Start: fast-forwards warm-up, shows the first test hour
    assert not at.exception
    labels = [m.label for m in at.metric]
    assert "Precision@10 (this hour)" in labels and "Hybrid lead over LFU" in labels
    assert len(at.dataframe) == 1
