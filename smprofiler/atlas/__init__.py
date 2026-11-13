"""Atlas-reference functional marker prediction.

Trains small models on the Allen Institute Human Immune Health
Atlas that predict, per databased study, the expected intensity of each functional
marker from a cell's identity marker values. Models are exported to ONNX so
they can serve as a null reference.
"""
