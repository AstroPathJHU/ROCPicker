import matplotlib.pyplot as plt, numpy as np, scipy.integrate

def optimize(*, X, Y, Xdot, Ydot, AUC, Lambda_guess, t_guess=None, guess=None, Lambda_scaling=1):
  NX = X(np.inf)
  NY = Y(np.inf)

  def fun(t, xy, params):
    x, y = xy
    Lambda, c1, c2 = params
    Lambda *= Lambda_scaling

    xdot = 2 * Xdot(t) / (+Lambda * y + c1)
    ydot = 2 * Ydot(t) / (-Lambda * x + c2)

    return [xdot, ydot]

  def bc(xyminusinfinity, xyplusinfinity, params):
    xminusinfinity, yminusinfinity = xyminusinfinity
    xplusinfinity, yplusinfinity = xyplusinfinity
    Lambda, c1, c2 = params
    Lambda *= Lambda_scaling

    bcs = [xminusinfinity, yminusinfinity, xplusinfinity-1, yplusinfinity-1, Lambda * AUC + c1 - 2*NX, -Lambda * (1-AUC) + c2 - 2*NY]
    return np.asarray(bcs[:-1])

  if guess is not None and t_guess is None:
    raise TypeError("Have to provide t_guess if you provide guess")
  if t_guess is None:
    t_guess = np.linspace(-10, 10, 1001)
  if guess is None:
    guess = xy_guess(X=X, Y=Y, t_guess=t_guess, AUC=AUC)

  np.testing.assert_equal(t_guess.shape[0], guess.shape[1])
  guess_dot = guess[:, 1:] - guess[:, :-1]
  guess_dot_left = np.concatenate((guess_dot, [[0], [0]]), axis=1)
  guess_dot_right = np.concatenate(([[0], [0]], guess_dot), axis=1)
  slc = np.any((abs(guess_dot_left)>1e-5) | (abs(guess_dot_right)>1e-5), axis=0)
  t_guess = t_guess[slc]
  guess = guess[:, slc]

  Lambda_guess /= Lambda_scaling
  c1_guess = 2*NX - Lambda_guess * AUC
  c2_guess = 2*NY + Lambda_guess * (1-AUC)
  params_guess = np.array([Lambda_guess, c1_guess, c2_guess])

  result = scipy.integrate.solve_bvp(fun=fun, bc=bc, x=t_guess, y=guess, p=params_guess, max_nodes=100000)

  t = (result.x[1:] + result.x[:-1]) / 2
  dt = (result.x[1:] - result.x[:-1])
  Xd, Yd = Xdot(t), Ydot(t)
  xd, yd = (result.yp[:, 1:] + result.yp[:, :-1]) / 2
  if np.min(xd) <= 0 or np.min(yd) <= 0:
    result.NLL = np.inf
  else:
    result.NLL = (
      - np.sum((Xd * np.log(xd) * dt)[xd > 0])
      - np.sum((Yd * np.log(yd) * dt)[yd > 0])
    )

  return result

def xy_guess(X, Y, t_guess, AUC):
  if not 0 <= AUC <= 1:
    raise ValueError(f"AUC={AUC} is not between 0 and 1")

  if callable(X):
    np.testing.assert_equal(X(-np.inf), 0)
    X = X(t_guess) / X(np.inf)
  if callable(Y):
    np.testing.assert_equal(Y(-np.inf), 0)
    Y = Y(t_guess) / Y(np.inf)
  XplusY = X + Y
  XminusY = X - Y

  xplusy = XplusY

  def xminusy_s(s):
    max_allowed_xminusy = np.min([xplusy, 2 - xplusy], axis=0)
    min_allowed_xminusy = -max_allowed_xminusy

    if s >= 0:
      xminusy = XminusY * (1-s) + min_allowed_xminusy * s
    elif s < 0:
      xminusy = XminusY * (1+s) + max_allowed_xminusy * (-s)

    return xminusy

  def AUCresidual_s(s):
    xminusy = xminusy_s(s)
    x = (xplusy + xminusy) / 2
    y = (xplusy - xminusy) / 2

    AUC_s = 1/2 * np.sum((x[1:] - x[:-1]) * (y[1:] + y[:-1]))
    return AUC_s - AUC

  try:
    np.testing.assert_allclose(AUCresidual_s(1), 1-AUC, atol=1e-4, rtol=0)
  except AssertionError:
    xminusy = xminusy_s(1)
    x = (xplusy + xminusy) / 2
    y = (xplusy - xminusy) / 2
    for _ in zip(x, y, strict=True):
      print(*_)
    plt.scatter(x, y)
    plt.show()
    raise
  try:
    np.testing.assert_allclose(AUCresidual_s(-1), -AUC, atol=1e-4, rtol=0)
  except AssertionError:
    xminusy = xminusy_s(-1)
    x = (xplusy + xminusy) / 2
    y = (xplusy - xminusy) / 2
    for _ in zip(x, y, strict=True):
      print(*_)
    plt.scatter(x, y)
    plt.show()
    raise

  if AUC == 1:
    s = 1
  elif AUC == 0:
    s = -1
  else:
    result = scipy.optimize.root_scalar(AUCresidual_s, method="bisect", bracket=[-1, 1])
    if not result.converged:
      raise RuntimeError("Optimize didn't converge")
    s = result.root

  xminusy = xminusy_s(s)
  x = (xplusy + xminusy) / 2
  y = (xplusy - xminusy) / 2
  return np.array([x, y])
