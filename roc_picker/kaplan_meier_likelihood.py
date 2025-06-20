"""
Kaplan-Meier curve with error bars calculated using the log-likelihood method.
"""

import collections.abc
import functools

import gurobipy as gp
from gurobipy import GRB
import matplotlib.pyplot as plt
import numpy as np
import scipy.optimize
import scipy.stats

from .discrete_optimization import (
  binary_search_sign_change,
  minimize_discrete_single_minimum,
)
from .kaplan_meier import (
  KaplanMeierBase,
  KaplanMeierInstance,
  KaplanMeierPatient,
  KaplanMeierPatientBase,
)

@functools.cache
def possible_probabilities(n_patients) -> np.ndarray:
  """
  Get the possible probabilities for the given patients.
  This is used to speed up the calculation of survival probabilities.
  """
  return np.unique([
    n_alive / n_total
    for n_total in range(n_patients + 1)
    for n_alive in range(n_total + 1)
    if n_total > 0
  ])

class KaplanMeierPatientNLL(KaplanMeierPatientBase):
  """
  A patient with a time and a parameter.
  The parameter is a log-likelihood function.
  """
  def __init__(
    self,
    time: float,
    censored: bool,
    parameter_nll: collections.abc.Callable[[float], float],
    observed_parameter: float,
  ):
    super().__init__(
      time=time,
      censored=censored,
      parameter=parameter_nll,
    )
    self.__observed_parameter = observed_parameter

  @property
  def parameter(self) -> collections.abc.Callable[[float], float]:
    """
    The parameter is a log-likelihood function.
    """
    return super().parameter

  @property
  def observed_parameter(self) -> float:
    """
    The observed value of the parameter.
    """
    return self.__observed_parameter

  @classmethod
  def from_count(
    cls,
    time: float,
    censored: bool,
    count: int,
  ):
    """
    Create a KaplanMeierPatientNLL from a count.
    The parameter NLL gives the negative log-likelihood to observe the count
    given the parameter, which is the mean of the Poisson distribution.
    """
    def parameter_nll(x: float) -> float:
      """
      The parameter is a log-likelihood function.
      """
      return -scipy.stats.poisson.logpmf(count, x).item()
    return cls(
      time=time,
      censored=censored,
      parameter_nll=parameter_nll,
      observed_parameter=count,
    )

  @classmethod
  def from_poisson_density(
    cls,
    time: float,
    censored: bool,
    numerator_count: int,
    denominator_area: float,
  ):
    """
    Create a KaplanMeierPatientNLL from a Poisson count
    divided by an area that is known precisely.
    """
    def parameter_nll(density: float) -> float:
      """
      The parameter is a log-likelihood function.
      """
      return -scipy.stats.poisson.logpmf(
        numerator_count,
        density * denominator_area,
      ).item()
    return cls(
      time=time,
      censored=censored,
      parameter_nll=parameter_nll,
      observed_parameter=numerator_count / denominator_area,
    )


  @classmethod
  def from_poisson_ratio(
    cls,
    time: float,
    censored: bool,
    numerator_count: int,
    denominator_count: int,
  ):
    """
    Create a KaplanMeierPatientNLL from a ratio of two counts.
    The parameter NLL gives the negative log-likelihood to observe the
    numberator and denominator counts given the parameter, which is the
    ratio of the two Poisson distribution means.  We do this by floating
    the denominator mean and fixing the numerator mean to the ratio
    times the denominator mean.  We then minimize the NLL to observe the
    numerator and denominator counts given the denominator mean.
    """
    def parameter_nll(ratio: float) -> float:
      if ratio < 0:
        return float('inf')  # Ratio must be positive

      # Define the NLL as a function of the (latent) denominator mean
      def nll_given_lambda_d(lambda_d: float) -> float:
        lambda_n = ratio * lambda_d
        # Poisson negative log-likelihoods
        nll_numerator = -scipy.stats.poisson.logpmf(numerator_count, lambda_n)
        nll_denominator = -scipy.stats.poisson.logpmf(denominator_count, lambda_d)
        return (nll_numerator + nll_denominator).item()

      # Optimize over lambda_d > 0
      result = scipy.optimize.minimize_scalar(
        nll_given_lambda_d,
        bounds=(1e-8, 1e6),
        method='bounded'
      )
      assert isinstance(result, scipy.optimize.OptimizeResult)
      return result.fun if result.success else float('inf')

    # Use the MLE ratio as the observed value
    observed_ratio = numerator_count / denominator_count if denominator_count > 0 else float('inf')

    return cls(
      time=time,
      censored=censored,
      parameter_nll=parameter_nll,
      observed_parameter=observed_ratio,
    )

  @property
  def nominal(self) -> KaplanMeierPatient:
    """
    The nominal value of the parameter.
    """
    return KaplanMeierPatient(
      time=self.time,
      censored=self.censored,
      parameter=self.observed_parameter,
    )

class ILPForKM:
  """
  Integer Linear Programming for a point on the Kaplan-Meier curve.
  """
  def __init__(
    self,
    all_patients: list[KaplanMeierPatientNLL],
    parameter_min: float,
    parameter_max: float,
    time_point: float,
  ):
    self.__all_patients = all_patients
    self.__parameter_min = parameter_min
    self.__parameter_max = parameter_max
    self.__time_point = time_point
    if not np.isfinite(self.__parameter_min and self.__parameter_min != -np.inf):
      raise ValueError("parameter_min must be finite or -inf")
    if not np.isfinite(self.__parameter_max and self.__parameter_max != np.inf):
      raise ValueError("parameter_max must be finite or inf")

  @property
  def all_patients(self) -> list[KaplanMeierPatientNLL]:
    """
    The list of all patients.
    """
    return self.__all_patients
  @property
  def parameter_min(self) -> float:
    """
    The minimum parameter value.
    """
    return self.__parameter_min
  @property
  def parameter_max(self) -> float:
    """
    The maximum parameter value.
    """
    return self.__parameter_max
  @property
  def time_point(self) -> float:
    """
    The time point for the Kaplan-Meier curve.
    """
    return self.__time_point

  def run_ILP( # pylint: disable=too-many-locals, too-many-statements, too-many-branches, too-many-arguments
    self,
    expected_probability: float,
    *,
    verbose=False,
    binomial_only=False,
    patient_wise_only=False,
    gurobi_rtol=1e-6,
  ):
    """
    Run the ILP for the given time point.
    """
    if not patient_wise_only and (expected_probability <= 0 or expected_probability >= 1):
      raise ValueError("expected_probability must be in (0, 1)")
    if expected_probability < 0 or expected_probability > 1:
      raise ValueError("expected_probability must be in [0, 1]")
    if binomial_only and patient_wise_only:
      raise ValueError("binomial_only and patient_wise_only cannot both be True")
    n_patients = len(self.all_patients)
    patient_times = np.array([p.time for p in self.all_patients])
    patient_censored = np.array([p.censored for p in self.all_patients])
    patient_alive = patient_times > self.time_point
    patient_in_study = patient_alive | ~patient_censored
    observed_parameters = np.array([p.observed_parameter for p in self.all_patients])

    binomial_penalty_table = {}
    for n_total in range(n_patients + 1):
      for n_alive in range(n_total + 1):
        if not patient_wise_only:
          penalty = -scipy.stats.binom.logpmf(n_alive, n_total, expected_probability)
          binomial_penalty_table[(n_alive, n_total)] = penalty.item()
        else:
          binomial_penalty_table[(n_alive, n_total)] = 0

    parameter_in_range = (
      (observed_parameters >= self.parameter_min)
      & (observed_parameters < self.parameter_max)
    )
    n_alive_obs = np.sum(patient_alive & parameter_in_range)
    n_total_obs = np.sum(patient_in_study & parameter_in_range)

    sgn_nll_penalty_for_patient_in_range = 2 * parameter_in_range - 1
    observed_nll = np.array([
      p.parameter(p.observed_parameter)
      for p in self.all_patients
    ])
    if np.isfinite(self.parameter_min):
      parameter_min_nll = np.array([
        p.parameter(self.parameter_min)
        for p in self.all_patients
      ])
    else:
      parameter_min_nll = np.full(n_patients, np.inf)
    if np.isfinite(self.parameter_max):
      parameter_max_nll = np.array([
        p.parameter(self.parameter_max)
        for p in self.all_patients
      ])
    else:
      parameter_max_nll = np.full(n_patients, np.inf)

    range_boundary_nll = np.min(
      np.array([parameter_min_nll, parameter_max_nll]),
      axis=0
    )
    abs_nll_penalty_for_patient_in_range = observed_nll - range_boundary_nll

    nll_penalty_for_patient_in_range = (
      sgn_nll_penalty_for_patient_in_range
      * abs_nll_penalty_for_patient_in_range
    )

    if binomial_only or not any(np.isfinite(range_boundary_nll)):
      if patient_wise_only:
        raise ValueError(
          "patient_wise_only cannot be True when binomial_only is True "
          "or when the parameter range is not finite"
        )
      binomial_penalty_val = binomial_penalty_table[(n_alive_obs, n_total_obs)]
      return scipy.optimize.OptimizeResult(
        x=2*binomial_penalty_val,
        success=True,
        n_total=n_total_obs,
        n_alive=n_alive_obs,
        binomial_2NLL=2*binomial_penalty_val,
        patient_2NLL=0,
        selected=parameter_in_range,
        model=None,
      )

    # ---------------------------
    # Gurobi model
    # ---------------------------

    model = gp.Model("Kaplan-Meier ILP")

    # Binary decision variables: x[i] = 1 if patient i is within the parameter range
    x = model.addVars(n_patients, vtype=GRB.BINARY, name="x")

    # Integer vars to count totals
    n_total = model.addVar(vtype=GRB.INTEGER, name="n_total")
    n_alive = model.addVar(vtype=GRB.INTEGER, name="n_alive")

    # Constraints to link to totals
    model.addConstr(n_total == gp.quicksum(x[i] for i in range(n_patients) if patient_in_study[i]))
    model.addConstr(n_alive == gp.quicksum(x[i] for i in range(n_patients) if patient_alive[i]))

    if not patient_wise_only:
      # ---------------------------
      # Indicator grid for binomial penalty
      # ---------------------------

      # Create binary indicators for each valid (n_alive, n_total)
      indicator_vars = {}
      for n_total_val in range(n_patients + 1):
        for n_alive_val in range(n_total_val + 1):
          ind = model.addVar(vtype=GRB.BINARY, name=f"ind_{n_alive_val}_{n_total_val}")
          indicator_vars[(n_alive_val, n_total_val)] = ind
          # Add indicator constraint: if active, enforce n_alive and n_total match
          model.addGenConstrIndicator(ind, True, n_alive - n_alive_val, GRB.EQUAL, 0)
          model.addGenConstrIndicator(ind, True, n_total - n_total_val, GRB.EQUAL, 0)

      # Only one pair can be active
      model.addConstr(gp.quicksum(indicator_vars.values()) == 1)

      # Binomial penalty
      binom_penalty = gp.quicksum(
        binomial_penalty_table[(na, nt)] * ind
        for (na, nt), ind in indicator_vars.items()
      )
    else:
      #no binomial penalty means there's nothing to constrain the observed
      #probability to the expected probability.  In that case, what does
      #it mean to get an NLL for the expected probability?
      #Instead, we constrain the observed probability to be at least as
      #far from the nominal observed probability as the expected
      #and find the minimum patient-wise NLL.
      binom_penalty = 0

      observed_probability = n_alive_obs / n_total_obs if n_total_obs > 0 else 0
      epsilon = np.min(np.diff(possible_probabilities(n_patients))) / 2

      if expected_probability > observed_probability:
        #n_alive / n_total >= expected_probability
        model.addConstr(n_alive >= expected_probability * n_total - epsilon)
      elif expected_probability < observed_probability:
        #n_alive / n_total <= expected_probability
        model.addConstr(n_alive <= expected_probability * n_total + epsilon)
      else:
        assert expected_probability == observed_probability

    # Patient-wise penalties
    patient_penalties = []
    for i in range(n_patients):
      if np.isfinite(nll_penalty_for_patient_in_range[i]):
        patient_penalties.append(nll_penalty_for_patient_in_range[i] * x[i])
      elif np.isposinf(nll_penalty_for_patient_in_range[i]):
        #the patient must be selected, so we add a constraint
        model.addConstr(x[i] == 1)
      elif np.isneginf(nll_penalty_for_patient_in_range[i]):
        #the patient must not be selected, so we add a constraint
        model.addConstr(x[i] == 0)
      else:
        raise ValueError(
          f"Unexpected NLL penalty for patient {i}: "
          f"{nll_penalty_for_patient_in_range[i]}"
        )

    patient_penalty = gp.quicksum(patient_penalties)

    # Objective: minimize total penalty
    model.setObjective(
      2 * (binom_penalty + patient_penalty),
      GRB.MINIMIZE,
    )

    if not verbose:
      # Suppress Gurobi output
      model.setParam('OutputFlag', 0)
    model.setParam("MIPGap", gurobi_rtol)

    model.optimize()

    if model.status != GRB.OPTIMAL:
      if model.status == GRB.INFEASIBLE and patient_wise_only:
        # If the model is infeasible, it means that no patients can be selected
        # while satisfying the constraints. This can happen if the expected
        # probability is too far from the observed probability and there are
        # some patients with infinite NLL penalties.
        return scipy.optimize.OptimizeResult(
          x=np.inf,
          success=False,
          n_total=0,
          n_alive=0,
          binomial_2NLL=np.inf,
          patient_2NLL=np.inf,
          patient_penalties=nll_penalty_for_patient_in_range,
          selected=[],
          model=model,
        )
      raise RuntimeError(
        f"Model optimization failed with status {model.status}. "
        "This may indicate an issue with the ILP formulation or the input data."
      )

    selected = [i for i in range(n_patients) if x[i].X > 0.5 and patient_in_study[i]]
    n_alive_val = np.rint(n_alive.X)
    n_total_val = np.rint(n_total.X)
    binomial_penalty_val = binomial_penalty_table[(n_alive_val, n_total_val)]

    patient_penalty_val = sum(
      nll_penalty_for_patient_in_range[i] * x[i].X
      for i in range(n_patients)
      if np.isfinite(nll_penalty_for_patient_in_range[i])
    )
    if verbose:
      print("Selected patients:", selected)
      print("n_total:          ", int(n_total_val))
      print("n_alive:          ", int(n_alive_val))
      print("Binomial penalty: ", binomial_penalty_val)
      print("Patient penalty:  ", patient_penalty_val)
      print("Total penalty:    ", model.ObjVal)

    return scipy.optimize.OptimizeResult(
      x=model.ObjVal,
      success=model.status == GRB.OPTIMAL,
      n_total=n_total_val,
      n_alive=n_alive_val,
      binomial_2NLL=2*binomial_penalty_val,
      patient_2NLL=2*patient_penalty_val,
      patient_penalties=nll_penalty_for_patient_in_range,
      selected=selected,
      model=model,
    )

class KaplanMeierLikelihood(KaplanMeierBase):
  """
  Kaplan-Meier curve with error bars calculated using the log-likelihood method.
  """
  def __init__(
    self,
    *,
    all_patients: list[KaplanMeierPatientNLL],
    parameter_min: float,
    parameter_max: float,
    endpoint_epsilon: float = 1e-6,
  ):
    self.__all_patients = all_patients
    self.__parameter_min = parameter_min
    self.__parameter_max = parameter_max
    self.__endpoint_epsilon = endpoint_epsilon

  @property
  def all_patients(self) -> list[KaplanMeierPatientNLL]:
    """
    The list of all patients.
    """
    return self.__all_patients

  @property
  def parameter_min(self) -> float:
    """
    The minimum parameter value.
    """
    return self.__parameter_min

  @property
  def parameter_max(self) -> float:
    """
    The maximum parameter value.
    """
    return self.__parameter_max

  @property
  def patient_times(self) -> frozenset:
    """
    The set of all patient times.
    """
    return frozenset(p.time for p in self.all_patients)

  @functools.cached_property
  def nominalkm(self) -> KaplanMeierInstance:
    """
    The nominal Kaplan-Meier curve.
    """
    return KaplanMeierInstance(
      all_patients=[p.nominal for p in self.all_patients],
      parameter_min=self.parameter_min,
      parameter_max=self.parameter_max,
    )

  def ilp_for_km(
    self,
    time_point: float,
  ):
    """
    Get the ILP for the given time point.
    """
    return ILPForKM(
      all_patients=self.all_patients,
      parameter_min=self.parameter_min,
      parameter_max=self.parameter_max,
      time_point=time_point,
    )

  def ilps_for_km(
    self,
    times_for_plot: np.ndarray | None,
  ):
    """
    Get the ILPs for the given time points.
    """
    if times_for_plot is None:
      times_for_plot = self.times_for_plot
    return [
      self.ilp_for_km(time_point=t)
      for t in times_for_plot
    ]

  def get_twoNLL_function(
    self,
    time_point: float,
    binomial_only=False,
    patient_wise_only=False,
    verbose=False,
  ) -> collections.abc.Callable[[float], float]:
    """
    Get the twoNLL function for the given time point.
    """
    ilp = self.ilp_for_km(time_point=time_point)
    @functools.cache
    def twoNLL(expected_probability: float) -> float:
      """
      The negative log-likelihood function.
      """
      result = ilp.run_ILP(
        expected_probability=expected_probability,
        binomial_only=binomial_only,
        patient_wise_only=patient_wise_only,
        verbose=verbose,
      )
      if not result.success:
        return np.inf
      return result.x
    return twoNLL

  @property
  def possible_probabilities(self) -> np.ndarray:
    """
    Get the possible probabilities for the given patients.
    """
    return possible_probabilities(
      n_patients=len(self.all_patients)
    )

  def best_probability( #pylint: disable=too-many-arguments
    self,
    time_point: float,
    *,
    binomial_only=False,
    patient_wise_only=False,
    gurobi_verbose=False,
    optimize_verbose=False,
  ) -> tuple[float, float]:
    """
    Find the expected probability that minimizes the negative log-likelihood
    for the given time point.
    """
    twoNLL = self.get_twoNLL_function(
      time_point=time_point,
      binomial_only=binomial_only,
      patient_wise_only=patient_wise_only,
      verbose=gurobi_verbose,
    )
    if patient_wise_only:
      return minimize_discrete_single_minimum(
        objective_function=twoNLL,
        possible_values=self.possible_probabilities,
        verbose=optimize_verbose,
      )
    result = scipy.optimize.minimize_scalar(
      twoNLL,
      bounds=(self.__endpoint_epsilon, 1 - self.__endpoint_epsilon),
      method='bounded',
    )
    assert isinstance(result, scipy.optimize.OptimizeResult)
    if not result.success:
      raise RuntimeError("Failed to find the best probability")
    return result.x, result.fun

  def survival_probabilities_likelihood( # pylint: disable=too-many-locals, too-many-branches, too-many-statements, too-many-arguments
    self,
    CLs: list[float],
    times_for_plot: np.ndarray,
    *,
    binomial_only=False,
    patient_wise_only=False,
    gurobi_verbose=False,
    optimize_verbose=False,
  ) -> tuple[np.ndarray, np.ndarray]:
    """
    Get the survival probabilities for the given quantiles.
    """
    best_probabilities = []
    survival_probabilities = []
    for t in times_for_plot:
      survival_probabilities_time_point = []
      survival_probabilities.append(survival_probabilities_time_point)
      twoNLL = self.get_twoNLL_function(
        time_point=t,
        binomial_only=binomial_only,
        patient_wise_only=patient_wise_only,
        verbose=gurobi_verbose,
      )
      # Find the expected probability that minimizes the negative log-likelihood
      # for the given time point
      try:
        best_prob, twoNLL_min = self.best_probability(
          time_point=t,
          binomial_only=binomial_only,
          patient_wise_only=patient_wise_only,
          gurobi_verbose=gurobi_verbose,
          optimize_verbose=optimize_verbose
        )
      except Exception as e:
        raise RuntimeError(
          f"Failed to find the best probability for time point {t}"
        ) from e
      best_probabilities.append(best_prob)

      for CL in CLs:
        if patient_wise_only and (t < min(self.patient_times) or t >= max(self.patient_times)):
          # If the time point is outside the range of patient times, we cannot
          # calculate a patient-wise survival probability.
          if t < min(self.patient_times):
            survival_probabilities_time_point.append((1, 1))
          else:
            survival_probabilities_time_point.append((0, 0))
          continue

        d2NLLcut = scipy.stats.chi2.ppf(CL, 1).item()
        def objective_function(
          expected_probability: float,
          twoNLL=twoNLL, twoNLL_min=twoNLL_min, d2NLLcut=d2NLLcut
        ) -> float:
          return twoNLL(expected_probability) - twoNLL_min - d2NLLcut
        np.testing.assert_almost_equal(
          objective_function(best_prob),
          -d2NLLcut,
        )

        if patient_wise_only:
          probs = self.possible_probabilities
          i_best = int(np.searchsorted(probs, best_prob))

          # Check edge case: upper bound
          if objective_function(probs[-1]) < 0:
            upper_bound = 1
          else:
            upper = binary_search_sign_change(
              objective_function=objective_function,
              probs=probs,
              lo=i_best,
              hi=len(probs) - 1,
            )
            if upper is None:
              raise RuntimeError("No upper sign change found")
            upper_bound = upper

          # Check edge case: lower bound
          if objective_function(probs[0]) < 0:
            lower_bound = 0
          else:
            lower = binary_search_sign_change(
              objective_function=objective_function,
              probs=probs,
              lo=0,
              hi=i_best,
            )
            if lower is None:
              raise RuntimeError("No lower sign change found")
            lower_bound = lower

        else:
          if objective_function(self.__endpoint_epsilon) < 0:
            lower_bound = 0
          else:
            lower_bound = scipy.optimize.brentq(
              objective_function,
              self.__endpoint_epsilon,
              best_prob,
              xtol=1e-6,
            )
          if objective_function(1 - self.__endpoint_epsilon) < 0:
            upper_bound = 1
          else:
            upper_bound = scipy.optimize.brentq(
              objective_function,
              best_prob,
              1 - self.__endpoint_epsilon,
              xtol=1e-6,
            )

        survival_probabilities_time_point.append((lower_bound, upper_bound))
    return np.array(best_probabilities), np.array(survival_probabilities)

  def plot( # pylint: disable=too-many-arguments, too-many-branches, too-many-statements
    self,
    *,
    times_for_plot=None,
    include_binomial_only=False,
    include_patient_wise_only=False,
    include_full_NLL=True,
    include_best_fit=True,
    nominal_label='Nominal',
    nominal_color='blue',
    CLs=None,
    CL_colors=None,
    CL_hatches=None,
    create_figure=True,
    close_figure=None,
    show=False,
    saveas=None,
  ): #pylint: disable=too-many-locals
    """
    Plots the Kaplan-Meier curves.
    """
    if include_binomial_only and include_patient_wise_only:
      raise ValueError("include_binomial_only and include_patient_wise_only cannot both be True")
    if not (include_binomial_only or include_patient_wise_only or include_full_NLL):
      raise ValueError(
        "At least one of include_binomial_only, include_patient_wise_only, "
        "or include_full_NLL must be True"
      )
    if times_for_plot is None:
      times_for_plot = self.times_for_plot
    if create_figure:
      plt.figure()
    nominal_x, nominal_y = self.nominalkm.points_for_plot(times_for_plot=times_for_plot)
    plt.plot(
      nominal_x,
      nominal_y,
      label=nominal_label,
      color=nominal_color,
      linestyle='--'
    )

    if CLs is None:
      CLs = [0.68, 0.95]

    if CL_colors is None:
      CL_colors = ['dodgerblue', 'skyblue', 'lightblue', 'lightcyan']
    if len(CLs) > len(CL_colors):
      raise ValueError(
        f"Not enough colors provided for {len(CLs)} CLs, "
        f"got {len(CL_colors)} colors"
      )
    CL_colors = CL_colors[:len(CLs)]

    if CL_hatches is None:
      CL_hatches = ['//', '\\\\', 'xx', '++']
    if (
      len(CLs) > len(CL_hatches)
      and include_full_NLL
      and (include_binomial_only or include_patient_wise_only)
    ):
      raise ValueError(
        f"Not enough hatches provided for {len(CLs)} CLs, "
        f"got {len(CL_hatches)} hatches"
      )
    CL_hatches = CL_hatches[:len(CLs)]

    CL_probabilities_subset = None
    best_probabilities = None
    CL_probabilities = None
    if include_full_NLL:
      best_probabilities, CL_probabilities = self.survival_probabilities_likelihood(
        CLs=CLs,
        times_for_plot=times_for_plot,
      )
    if include_binomial_only:
      (
        best_probabilities_binomial, CL_probabilities_binomial
      ) = self.survival_probabilities_likelihood(
        CLs=CLs,
        times_for_plot=times_for_plot,
        binomial_only=True,
      )
      if include_full_NLL:
        CL_probabilities_subset = CL_probabilities_binomial
      else:
        best_probabilities = best_probabilities_binomial
        CL_probabilities = CL_probabilities_binomial
    if include_patient_wise_only:
      (
        best_probabilities_patient_wise, CL_probabilities_patient_wise
      ) = self.survival_probabilities_likelihood(
        CLs=CLs,
        times_for_plot=times_for_plot,
        patient_wise_only=True,
      )
      if include_full_NLL:
        CL_probabilities_subset = CL_probabilities_patient_wise
      else:
        best_probabilities = best_probabilities_patient_wise
        CL_probabilities = CL_probabilities_patient_wise

    assert best_probabilities is not None
    assert CL_probabilities is not None

    best_x, best_y = self.get_points_for_plot(times_for_plot, best_probabilities)
    if include_best_fit:
      plt.plot(
        best_x,
        best_y,
        label="Best Probability",
        color='red',
        linestyle='--'
      )

    for CL, color, (p_minus, p_plus) in zip(
      CLs,
      CL_colors,
      CL_probabilities.transpose(1, 2, 0),
      strict=True,
    ):
      x_minus, y_minus = self.get_points_for_plot(times_for_plot, p_minus)
      x_plus, y_plus = self.get_points_for_plot(times_for_plot, p_plus)
      np.testing.assert_array_equal(x_minus, x_plus)

      plt.fill_between(
        x_minus,
        y_minus,
        y_plus,
        color=color,
        alpha=0.5,
        label=f'{CL:.6%} CL' if CL > 0.9999 else f'{CL:.2%} CL' if CL > 0.99 else f'{CL:.0%} CL',
      )

    if CL_probabilities_subset is not None:
      subset_label = "Binomial only" if include_binomial_only else "Patient-wise only"
      for CL, color, hatch, (p_minus_subset, p_plus_subset) in zip(
        CLs,
        CL_colors,
        CL_hatches,
        CL_probabilities_subset.transpose(1, 2, 0),
        strict=True,
      ):
        x_minus_subset, y_minus_subset = self.get_points_for_plot(times_for_plot, p_minus_subset)
        x_plus_subset, y_plus_subset = self.get_points_for_plot(times_for_plot, p_plus_subset)
        np.testing.assert_array_equal(x_minus_subset, x_plus_subset)

        plt.fill_between(
          x_minus_subset,
          y_minus_subset,
          y_plus_subset,
          edgecolor=color,
          facecolor='none',
          hatch=hatch,
          alpha=0.5,
          label=(
            (f'{CL:.6%} CL' if CL > 0.9999 else f'{CL:.2%} CL' if CL > 0.99 else f'{CL:.0%} CL')
            + f'({subset_label})'
          ),
        )

    if create_figure:
      plt.xlabel("Time")
      plt.ylabel("Survival Probability")
      plt.legend()
      plt.title("Kaplan-Meier Curves")
      plt.grid()
      if saveas is not None:
        plt.savefig(saveas)
      if show:
        plt.show()
      if close_figure:
        plt.close()
