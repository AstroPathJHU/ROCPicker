"""
Kaplan-Meier curves with systematic uncertainties, using the Monte Carlo method.
"""

import abc
import functools
import numbers

import matplotlib.pyplot as plt
import numpy as np

class KaplanMeierPatientBase(abc.ABC):
  """
  Base class for Kaplan-Meier patients.
  It contains the survival time and the parameter used to group the patients.
  """
  def __init__(self, time: float, censored: bool, parameter):
    self.__time = time
    self.__censored = censored
    self.__parameter = parameter
  @property
  def time(self):
    """
    Returns the survival time of the patient.
    """
    return self.__time
  @property
  def censored(self) -> bool:
    """
    Returns True if the patient is censored, False otherwise.
    """
    return self.__censored
  @property
  def parameter(self):
    """
    Returns the parameter used to group the patients.
    """
    return self.__parameter

class KaplanMeierPatient(KaplanMeierPatientBase):
  """
  Class to represent a patient with their survival time and parameter.
  """
  def __init__(self, time: float, censored: bool, parameter: float):
    super().__init__(time=time, censored=censored, parameter=parameter)
    if not isinstance(parameter, (numbers.Number)):
      raise TypeError("Parameter must be a number")

  @property
  def parameter(self) -> float:
    """
    Returns the parameter used to group the patients.
    """
    return super().parameter

class KaplanMeierBase(abc.ABC):
  """
  Base class for Kaplan-Meier curves with some utility functions.
  """
  @property
  @abc.abstractmethod
  def patient_times(self) -> frozenset[float]:
    """
    Returns the survival times of the patients.
    """
  @functools.cached_property
  def times_for_plot(self):
    """
    Returns the survival times for the Kaplan-Meier curve.
    The times are the unique survival times of the patients,
    plus a point at 0 and a point beyond the last time.
    """
    times_for_plot = sorted(self.patient_times)
    times_for_plot = np.array([0] + times_for_plot + [times_for_plot[-1] * 1.1])
    return times_for_plot

  @staticmethod
  def get_points_for_plot(times_for_plot, survival_probabilities):
    """
    Return (x, y) points for the Kaplan-Meier curve based on the
    survival probabilities at each time.
    Each time enters twice in the plot in order to have a step function.
    """
    x = [times_for_plot[0]]
    y = [survival_probabilities[0]]
    for prevprob, time, prob in zip(
      survival_probabilities[:-1],
      times_for_plot[1:],
      survival_probabilities[1:],
      strict=True
    ):
      x.append(time)
      y.append(prevprob)
      x.append(time)
      y.append(prob)
    return np.array(x), np.array(y)

class KaplanMeierInstance(KaplanMeierBase):
  """
  Class to represent a Kaplan-Meier curve.
  It contains a list of patients with their survival times and parameters.
  The patients are filtered based on a parameter range.

  Parameters
  ----------
  all_patients : list of KMPatient
    List of all patients with their survival times and parameters.
  """
  def __init__(
    self,
    all_patients: list[KaplanMeierPatient],
    parameter_min: float = -np.inf,
    parameter_max: float = np.inf
  ):
    self.__all_patients = all_patients
    self.__parameter_min = parameter_min
    self.__parameter_max = parameter_max


  @property
  def all_patients(self):
    """
    Returns all the patients before filtering.
    """
    return self.__all_patients
  @property
  def patients(self):
    """
    Returns the patients who enter the Kaplan-Meier curve.
    The patients are filtered based on the parameter range.
    """
    return [
      p for p in self.all_patients
      if self.__parameter_min <= p.parameter < self.__parameter_max
    ]

  @property
  def patient_times(self):
    """
    Returns the survival times of the patients.
    """
    patients = self.patients
    patient_times = frozenset({p.time for p in patients})
    return patient_times

  def survival_probabilities(self, times_for_plot=None):
    """
    Returns the points for the Kaplan-Meier curve.
    The points are the survival times and the survival probabilities.
    """
    patients = self.patients
    patient_times = np.array([p.time for p in patients])
    patient_censored = np.array([p.censored for p in patients])
    if times_for_plot is None:
      times_for_plot = self.times_for_plot

    survival_probabilities = np.zeros(len(times_for_plot))
    for i, t in enumerate(times_for_plot):
      patient_alive = patient_times > t
      n_patients = np.count_nonzero(patient_alive | ~patient_censored)
      still_alive = np.count_nonzero(patient_alive)
      try:
        survival_probabilities[i] = still_alive / n_patients
      except ZeroDivisionError:
        #after everyone is censored: keep the last survival probability
        survival_probabilities[i] = survival_probabilities[i - 1]

    return survival_probabilities

  def points_for_plot(self, times_for_plot=None):
    """
    Returns the points for the Kaplan-Meier curve.
    The points are the survival times and the survival probabilities.
    """
    if times_for_plot is None:
      times_for_plot = self.times_for_plot
    survival_probabilities = self.survival_probabilities(times_for_plot)
    return self.get_points_for_plot(times_for_plot, survival_probabilities)

class KaplanMeierPlot(KaplanMeierBase):
  """
  Class to represent a set of Kaplan-Meier curves.
  It contains a list of patients with their survival times and parameters.
  The patients are filtered based on a parameter range, and each patient
  enters a different Kaplan-Meier curve.

  Parameters
  ----------
  all_patients : list of KMPatient
    List of all patients with their survival times and parameters.
  thresholds : list of float
    List of thresholds to filter the patients.
  """
  def __init__(
    self,
    all_patients: list[KaplanMeierPatient],
    thresholds: list[float],
  ):
    self.__all_patients = all_patients
    self.__thresholds = [-np.inf] + sorted(thresholds) + [np.inf]
    self.__curves = []
    for i in range(len(self.__thresholds) - 1):
      self.__curves.append(
        KaplanMeierInstance(
          all_patients,
          self.__thresholds[i],
          self.__thresholds[i + 1],
        )
      )

  @property
  def all_patients(self):
    """
    Returns the patients with their survival times and parameters.
    """
    return self.__all_patients

  def plot(self):
    """
    Plots the Kaplan-Meier curves.
    """
    plt.figure()
    for i, curve in enumerate(self.__curves):
      x, y = curve.points_for_plot(times_for_plot=self.times_for_plot)
      print(x, y)
      plt.plot(
        x,
        y,
        #where='post',
        label=f"Curve {i + 1}: {self.__thresholds[i]} <= parameter < {self.__thresholds[i + 1]}"
      )

    plt.xlabel("Time")
    plt.ylabel("Survival Probability")
    plt.title("Kaplan-Meier Curves")
    plt.legend()
    plt.grid()
    plt.show()

  @property
  def patient_times(self):
    """
    Returns the survival times of the patients.
    """
    return frozenset.union(
      *[kmi.patient_times for kmi in self.__curves]
    )
