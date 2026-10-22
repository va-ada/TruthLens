"""The benchmark's metric code must be right before its numbers mean anything."""
import json

import pytest

from backend.evaluation import run_benchmark as rb


def _row(label, predicted):
    return {"label": label, "predicted": predicted, "latency_s": 1.0}


def test_perfect_predictions():
    m = rb.report([_row("TRUE", "TRUE"), _row("FALSE", "FALSE"), _row("NEI", "NEI")])
    assert m["accuracy"] == 1.0 and m["macro_f1"] == 1.0


def test_confusion_matrix_and_per_class():
    rows = [_row("TRUE", "TRUE"), _row("TRUE", "NEI"), _row("FALSE", "TRUE"), _row("NEI", "NEI")]
    m = rb.report(rows)
    assert m["accuracy"] == 0.5
    assert m["confusion_matrix"]["TRUE"] == {"TRUE": 1, "FALSE": 0, "NEI": 1}
    assert m["confusion_matrix"]["FALSE"]["TRUE"] == 1
    assert m["per_class"]["TRUE"]["precision"] == 0.5 and m["per_class"]["TRUE"]["recall"] == 0.5
    assert m["per_class"]["NEI"]["precision"] == 0.5 and m["per_class"]["NEI"]["recall"] == 1.0
    assert m["per_class"]["FALSE"]["f1"] == 0.0


def test_errors_excluded_but_counted():
    m = rb.report([_row("TRUE", "TRUE"), _row("FALSE", "ERROR")])
    assert m["errors"] == 1 and m["accuracy"] == 1.0 and m["n"] == 2


def test_every_canonical_verdict_maps_to_a_class():
    from backend.models.schemas import Verdict
    assert {v.value for v in Verdict} == set(rb.VERDICT_TO_CLASS)


@pytest.mark.parametrize("name", ["benchmark_dataset.json", "datasets/fever_dev_sample.jsonl"])
def test_datasets_load_with_valid_labels(name):
    rows = rb.load_dataset(rb.HERE / name)
    assert rows and all(r["claim"] and r["label"] in rb.CLASSES for r in rows)


def test_fever_sample_is_balanced():
    rows = rb.load_dataset(rb.HERE / "datasets" / "fever_dev_sample.jsonl")
    counts = {c: sum(r["label"] == c for r in rows) for c in rb.CLASSES}
    assert counts == {"TRUE": 50, "FALSE": 50, "NEI": 50}
