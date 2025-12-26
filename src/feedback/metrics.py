from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class AnnotationRecord:
    """Single annotation record for agreement calculations."""
    item_id: str
    annotator_id: str
    label: str


def build_annotation_matrix(
    records: list[AnnotationRecord],
) -> tuple[list[list[str | None]], list[str], list[str]]:
    """Build an item x annotator matrix of labels."""
    item_ids = sorted({r.item_id for r in records})
    annotator_ids = sorted({r.annotator_id for r in records})

    item_index = {item_id: idx for idx, item_id in enumerate(item_ids)}
    annotator_index = {ann_id: idx for idx, ann_id in enumerate(annotator_ids)}

    matrix: list[list[str | None]] = [
        [None for _ in annotator_ids] for _ in item_ids
    ]

    for record in records:
        i = item_index[record.item_id]
        j = annotator_index[record.annotator_id]
        matrix[i][j] = record.label

    return matrix, item_ids, annotator_ids


def cohen_kappa(labels_a: list[str], labels_b: list[str]) -> float | None:
    """Compute Cohen's kappa for two aligned label lists."""
    if len(labels_a) != len(labels_b) or not labels_a:
        return None

    n = len(labels_a)
    observed = sum(1 for a, b in zip(labels_a, labels_b) if a == b) / n

    counts_a = Counter(labels_a)
    counts_b = Counter(labels_b)
    expected = 0.0
    for label in set(counts_a) | set(counts_b):
        expected += (counts_a.get(label, 0) / n) * (counts_b.get(label, 0) / n)

    if expected >= 1.0:
        return 1.0

    return (observed - expected) / (1.0 - expected)


def average_pairwise_kappa(matrix: list[list[str | None]]) -> float | None:
    """Compute average pairwise Cohen's kappa across annotators."""
    if not matrix or not matrix[0]:
        return None

    annotator_count = len(matrix[0])
    kappas: list[float] = []

    for i in range(annotator_count):
        for j in range(i + 1, annotator_count):
            labels_a = []
            labels_b = []
            for row in matrix:
                a = row[i]
                b = row[j]
                if a is None or b is None:
                    continue
                labels_a.append(a)
                labels_b.append(b)
            kappa = cohen_kappa(labels_a, labels_b)
            if kappa is not None:
                kappas.append(kappa)

    if not kappas:
        return None
    return sum(kappas) / len(kappas)


def krippendorff_alpha_nominal(matrix: list[list[str | None]]) -> float | None:
    """Compute Krippendorff's alpha for nominal labels."""
    total_counts: Counter[str] = Counter()
    total_n = 0
    do_sum = 0.0

    for row in matrix:
        labels = [label for label in row if label is not None]
        n_i = len(labels)
        if n_i <= 1:
            continue
        counts = Counter(labels)
        total_counts.update(counts)
        total_n += n_i
        disagree = sum(count * (n_i - count) for count in counts.values())
        do_sum += disagree / (n_i - 1)

    if total_n <= 1:
        return None

    do = do_sum / total_n
    de_num = sum(count * (total_n - count) for count in total_counts.values())
    de = de_num / (total_n * (total_n - 1))

    if de == 0.0:
        return 1.0 if do == 0.0 else 0.0

    return 1.0 - (do / de)
