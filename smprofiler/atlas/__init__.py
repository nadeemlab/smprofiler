"""Atlas-reference functional marker prediction.

Trains small regression models on the Allen Institute Human Immune Health
Atlas that predict, per SPT study, the expected intensity of each functional
marker from a cell's identity marker values. Models are exported to ONNX so
they can serve as a null reference for "atlas-relative positive" calls.

The training pipeline lives in :mod:`smprofiler.atlas.training`; the command
line entry point is ``smprofiler atlas train-atlas-models``.
"""
