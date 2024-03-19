import matplotlib.pyplot as plt, numpy as np
import delta_functions

responders = np.linspace(-10, 10, 3)
nonresponders = responders+2.5

def plot_params(responders, nonresponders, *, skip_aucs=[]):
  target_aucs = []
  aucs = []
  delta_aucs = []
  L = []
  c1 = []
  c5 = []
  NLL = []

  t = np.asarray(sorted(set(responders) | set(nonresponders) | {-np.inf, np.inf}))

  @np.vectorize
  def X(t): return sum(1 for n in nonresponders if n < t)
  @np.vectorize
  def Y(t): return sum(1 for r in responders if r < t)

  xx = X(t) / len(nonresponders)
  yy = Y(t) / len(responders)
  AUC = 1/2 * np.sum((yy[1:]+yy[:-1]) * (xx[1:] - xx[:-1]))

  linspaces = [
    [AUC] + [_ for _ in np.linspace(0, 1, 21) if _ >= AUC],
    [AUC] + [_ for _ in np.linspace(1, 0, 21) if _ <= AUC],
  ]

  plt.figure(figsize=(5, 5))
  for linspace in linspaces:
    last_failed = False
    for target_auc in linspace:
      print(target_auc)
      if target_auc in skip_aucs: continue
      result = delta_functions.findxy(responders, nonresponders, AUC=target_auc, c1_guess=1, c5_guess=1, Lambda_guess=1)
      x = result.x
      y = result.y
      xx = x(t)
      yy = y(t)
      auc = 1/2 * np.sum((yy[1:]+yy[:-1]) * (xx[1:] - xx[:-1]))
      delta_auc = auc - target_auc
      if abs(delta_auc) > 1e-4 or abs(xx[-1]-1) > 1e-4 or abs(yy[-1]-1) > 1e-4:
        print("failed", target_auc)
        if last_failed:
          break
        else:
          last_failed = True
          continue
      last_failed = False
      plt.scatter(xx, yy, label=f"{target_auc:.3g}")
      target_aucs.append(target_auc)
      delta_aucs.append(delta_auc)
      c1.append(result.c1)
      c5.append(result.c5)
      L.append(result.Lambda)
      NLL.append(result.NLL)
  plt.legend()
  plt.show()
  plt.figure(figsize=(5, 5))
  plt.scatter(target_aucs, c1, label="$c_{1}$")
  plt.scatter(target_aucs, c5, label="$c_{5}$")
  plt.scatter(target_aucs, L, label=r"$\Lambda$")
  plt.ylim(-10, 100)
  plt.legend()
  plt.show()

  target_aucs = np.asarray(target_aucs)
  deltaNLL = np.asarray(NLL)
  deltaNLL -= np.nanmin(deltaNLL)
  plt.figure(figsize=(5,5))
  plt.scatter(target_aucs, 2*deltaNLL, label="$-2\Delta\ln{L}$")
  slc = np.isclose(deltaNLL, np.nanmin(deltaNLL))
  plt.scatter(target_aucs[slc], 2*deltaNLL[slc], label="best fit")
  xlow, xhigh = plt.xlim()
  plt.plot([xlow, xhigh], [1, 1], label="68% CL")
  plt.plot([xlow, xhigh], [3.84, 3.84], label="95% CL")
  plt.legend()
  plt.xlabel("AUC")
  plt.ylabel("$-2\Delta\ln{L}$")
  plt.show()
