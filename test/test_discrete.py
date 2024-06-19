import numpy as np, pathlib, pickle
import roc_picker.discrete

here = pathlib.Path(__file__).parent
docsfolder = here.parent/"docs"

responders = [1, 1, 2, 2, 3, 9, 10]
nonresponders = [2, 3, 3, 4, 6, 8, 9, 10, 10, 10, 10, 11, 12, 13]

def main():
  rocs = roc_picker.discrete.DiscreteROC(
    responders=responders,
    nonresponders=nonresponders,
    flip_sign=False,
    check_validity=True,
  ).plot_roc(
    npoints=100,
    yupperlim=20,
    rocfilename=docsfolder/"discrete_exampleroc.pdf",
    scanfilename=docsfolder/"discrete_scan.pdf",
    rocerrorsfilename=docsfolder/"discrete_exampleroc_errors.pdf",
    show=False,
  )

  rocs_flip = roc_picker.discrete.DiscreteROC(
    responders=responders,
    nonresponders=nonresponders,
    flip_sign=True,
    check_validity=True,
  ).plot_roc(
    npoints=100,
    yupperlim=20,
    show=False,
  )

  def hack_fix_roc(roc):
    if roc.x[0] == roc.x[1] and roc.y[0] == roc.y[1]:
      roc["x"] = roc.x[1:]
      roc["y"] = roc.y[1:]
    if roc.x[-1] == roc.x[-2] and roc.y[-1] == roc.y[-2]:
      roc["x"] = roc.x[:-1]
      roc["y"] = roc.y[:-1]

  tolerance = {"atol": 1e-6, "rtol": 1e-6}

  for k in set(rocs) | set(rocs_flip):
    roc = rocs[k]
    flipk = {
      "nominal": "nominal",
      "p68": "m68",
      "p95": "m95",
      "m68": "p68",
      "m95": "p95",
    }[k]
    flip = rocs_flip[flipk]
    np.testing.assert_allclose(np.array([roc.x, roc.y]), 1-np.array([flip.x, flip.y])[:,::-1], **tolerance)
    np.testing.assert_allclose(roc.AUC, 1-flip.AUC, **tolerance)
    np.testing.assert_allclose(roc.NLL, flip.NLL, **tolerance)

  try:
    with open(here/"reference"/"discrete.pkl", "rb") as f:
      refs = pickle.load(f)
    for k in set(rocs) | set(refs):
      roc = rocs[k]
      ref = refs[k]
      hack_fix_roc(ref)
      np.testing.assert_allclose(np.array([roc.x, roc.y]), np.array([ref.x, ref.y]), **tolerance)
      np.testing.assert_allclose(roc.AUC, ref.AUC, **tolerance)
      np.testing.assert_allclose(roc.NLL, ref.NLL, **tolerance)
  except:
    with open(here/"test_output"/"discrete.pkl", "wb") as f:
      pickle.dump(rocs, f)
    raise

if __name__ == "__main__":
  main()
