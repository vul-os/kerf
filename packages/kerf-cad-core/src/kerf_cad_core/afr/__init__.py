"""kerf_cad_core.afr — Automatic Feature Recognition (AFR) subpackage."""
from kerf_cad_core.afr.recognize import recognize_features
from kerf_cad_core.afr.dag import (
    AFRFeatureDAG,
    afr_to_dag,
    afr_dag_to_feature_log,
    emit_feature_log,
)

__all__ = [
    "recognize_features",
    "AFRFeatureDAG",
    "afr_to_dag",
    "afr_dag_to_feature_log",
    "emit_feature_log",
]
