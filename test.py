import matplotlib.pyplot as plt, numpy as np, scipy.integrate, scipy.stats
import roc_auc

h = 0.3

def X(t):
  return (scipy.stats.norm.cdf(t, loc=0, scale=h) + 2*scipy.stats.norm.cdf(t, loc=2, scale=h)) / 3
def Y(t):
  return (scipy.stats.norm.cdf(t, loc=1, scale=h) + 2*scipy.stats.norm.cdf(t, loc=-2, scale=h)) / 3
def Xdot(t):
  return (scipy.stats.norm.pdf(t, loc=0, scale=h) + 2*scipy.stats.norm.pdf(t, loc=2, scale=h)) / 3
def Ydot(t):
  return (scipy.stats.norm.pdf(t, loc=1, scale=h) + 2*scipy.stats.norm.pdf(t, loc=-2, scale=h)) / 3

t_plot = np.linspace(-10, 10, 1001)
dt_plot = t_plot[1] - t_plot[0]
AUC = np.sum(Y(t_plot) * Xdot(t_plot)) * dt_plot

def run(target_AUC, verbose=True, Lambda_guess=None):
  xy_guess = roc_auc.xy_guess(X=X, Y=Y, t_plot=t_plot, AUC=target_AUC)
  if Lambda_guess is None:
    if target_AUC < AUC:
      Lambda_guess = 2
    else:
      Lambda_guess = -2 
  optimize_result = roc_auc.optimize(X=X, Y=Y, Xdot=Xdot, Ydot=Ydot, AUC=target_AUC, Lambda_scaling=1, Lambda_guess=Lambda_guess)
  x, y = xy = optimize_result.y
  Lambda, c1, c2 = params = optimize_result.p

  if verbose:  
    plt.scatter(X(t_plot), Y(t_plot), label="X, Y")
    plt.scatter(xy_guess[0], xy_guess[1], label="guess")
    plt.scatter(xy[0], xy[1], label="optimized")
    print("=========================")
    print("should be 0:", x[0], y[0])
    print("should be 1:", x[-1], y[-1])
    print("should be equal:", target_AUC, 1/2 * np.sum((y[1:]+y[:-1]) * (x[1:] - x[:-1])))
    print("should be equal:", c1, 2 - Lambda*target_AUC)
    print("should be equal:", c2, 2 + Lambda*(1-target_AUC))
    print("=========================")
    plt.legend()
    plt.show()
  
  return optimize_result

def plot_params():
  target_aucs = []
  aucs = []
  delta_aucs = []
  L = []
  c1 = []
  c2 = []
  for target_auc in np.linspace(AUC+0.1, AUC-0.3, 401):
    result = run(target_auc, verbose=False)
    print(target_auc, result.success)
    if result.success:
      target_aucs.append(target_auc)
      x, y = result.y
      auc = 1/2 * np.sum((y[1:]+y[:-1]) * (x[1:] - x[:-1]))
      delta_aucs.append(auc - target_auc)
      L.append(result.p[0])
      c1.append(result.p[1])
      c2.append(result.p[2])
  plt.scatter(target_aucs, delta_aucs, label="$\Delta$AUC")
  plt.scatter(target_aucs, L, label="$\Lambda$")
  plt.scatter(target_aucs, c1, label="$c_1$")
  plt.scatter(target_aucs, c2, label="$c_2$")
  plt.legend()
  plt.show()
  return target_aucs, delta_aucs, L, c1, c2
