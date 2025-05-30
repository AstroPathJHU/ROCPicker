# ROC Picker

![ROC Picker logo](logo.png)

Welcome!

ROC Picker is a software package for propagating statistical and systematic
uncertainties in a biomedical analysis.

## Full documentation

For detailed information and examples, please see the documentation.
The source is in the `docs/` folder, and you can download the output
(latest version from the `main` branch, compiled by Github Actions) from
[this link](https://nightly.link/AstroPathJHU/ROCPicker/workflows/test_and_docs/main/docs.zip).

## Quick start

To install ROC Picker, clone the repository, enter its folder, and do
```
pip install .
```

Here is a simple example:
```
from roc_picker.discrete import DiscreteROC
responders = [1, 1, 2, 3, 9, 10]
nonresponders = [2, 3, 3, 4, 6, 8, 9, 10, 10, 10, 10, 11, 12, 13]
DiscreteROC(
  responders=responders,
  nonresponders=nonresponders,
).make_plots(
  npoints=100,
  yupperlim=20,
  #if you want to save the output plots
  filenames=("roc.pdf", "auc_scan.pdf", "roc_errors.pdf"),
  #if you're running in a jupyter notebook or similar, and want to see the plots
  show=True,
)
```
