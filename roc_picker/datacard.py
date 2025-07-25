#pylint: disable=too-many-lines

"""
A datacard class to specify the inputs to ROC Picker.
This is heavily modeled after the datacard format used in the Higgs Combine Tool.
"""

import abc
import argparse
import functools
import itertools
import pathlib

import numpy as np
import scipy.stats

from .delta_functions import DeltaFunctionsROC
from .discrete import DiscreteROC
from .kaplan_meier_likelihood import (
  KaplanMeierLikelihood,
  KaplanMeierPatientNLL,
  KaplanMeierPlotConfig,
)
from .systematics_mc import DistributionBase, DummyDistribution, ROCDistributions, ScipyDistribution

class Response:
  """
  A class to represent the response of a patient.
  """
  def __init__(self, response):
    self.response = response
    if self.response not in ["responder", "non-responder"]:
      raise ValueError(f"Invalid response: {self.response}")

  def __repr__(self):
    return f"Response(response={self.response})"

  def __str__(self):
    return f"Response: {self.response}"

class Observable(abc.ABC): # pylint: disable=too-few-public-methods
  """
  An abstract base class for observables.
  """
  @abc.abstractmethod
  def _create_observable_distribution(self) -> DistributionBase:
    """
    Abstract method to get the observable distribution.
    """

  @functools.cached_property
  def observable_distribution(self) -> DistributionBase:
    """
    Get the observable distribution.
    """
    return self._create_observable_distribution()

  @abc.abstractmethod
  def patient_nll(self, time, censored) -> KaplanMeierPatientNLL:
    """
    Get the patient NLL for the likelihood method.
    """

class FixedObservable(Observable):
  """
  A class to represent a fixed observable.
  """
  def __init__(self, value: float):
    self.value = value

  def __repr__(self):
    return f"{type(self).__name__}(value={self.value})"

  def _create_observable_distribution(self):
    """
    Get the observable distribution for a fixed observable.
    """
    return DummyDistribution(self.value)

  def __eq__(self, other):
    if not isinstance(other, FixedObservable):
      return NotImplemented
    return self.value == other.value

  def __str__(self):
    return str(self.value)

  def patient_nll(self, time, censored) -> KaplanMeierPatientNLL:
    """
    Get the patient NLL for the likelihood method.
    """
    return KaplanMeierPatientNLL.from_fixed_observable(
      observable=self.value,
      censored=censored,
      time=time,
    )

class PoissonObservable(Observable):
  """
  A class to represent a Poisson observable.
  """
  def __init__(self, count: int, unique_id: int):
    self.count = count
    if not isinstance(self.count, int) or self.count < 0:
      raise ValueError(f"Invalid count: {self.count}")
    self.unique_id = unique_id
    if not isinstance(self.unique_id, int):
      raise ValueError(f"Invalid unique_id: {self.unique_id}")

  def __repr__(self):
    return f"{type(self).__name__}(count={self.count})"

  def _create_observable_distribution(self):
    """
    Get the observable distribution for a Poisson observable.
    """
    return ScipyDistribution(
      nominal=self.count,
      scipydistribution=scipy.stats.poisson(mu=self.count),
      unique_id=self.unique_id,
    )

  def patient_nll(self, time, censored) -> KaplanMeierPatientNLL:
    """
    Get the patient NLL for the likelihood method.
    """
    return KaplanMeierPatientNLL.from_count(
      count=self.count,
      censored=censored,
      time=time,
    )

class PoissonDensityObservable(Observable):
  """
  A class to represent a Poisson density observable:
  a count divided by a fixed area.

  Parameters:
  -----------
  numerator (int): The count for the numerator.
  area (float): The fixed area for the denominator.
  unique_id_numerator (int): A unique ID for the numerator distribution.
  """

  def __init__(
    self,
    *,
    numerator: int | None = None,
    denominator: float | None = None,
    unique_id_numerator: int
  ):
    self.__numerator = None
    self.__denominator = None
    self.numerator = numerator
    self.denominator = denominator
    self.unique_id_numerator = unique_id_numerator

    if not isinstance(unique_id_numerator, int):
      raise ValueError(f"Invalid unique_id_numerator: {unique_id_numerator}")

  def __repr__(self):
    return f"{type(self).__name__}(numerator={self.numerator}, area={self.denominator})"

  @property
  def numerator(self):
    """
    Get the count for the numerator.
    """
    return self.__numerator
  @numerator.setter
  def numerator(self, value):
    if value is None:
      return
    if not isinstance(value, int) or value < 0:
      raise ValueError(f"Invalid numerator: {value}")
    if self.__numerator is not None and self.__numerator != value:
      raise ValueError("Numerator already set")
    self.__numerator = value

  @property
  def denominator(self):
    """
    Get the fixed area for the denominator.
    """
    return self.__denominator
  @denominator.setter
  def denominator(self, value):
    if value is None:
      return
    if not isinstance(value, (int, float)) or value <= 0:
      raise ValueError(f"Invalid denominator: {value}")
    if self.__denominator is not None and self.__denominator != value:
      raise ValueError("Denominator already set")
    self.__denominator = value
  def _create_observable_distribution(self):
    """
    Get the observable distribution for a Poisson density observable.
    """
    if self.numerator is None or self.denominator is None:
      raise ValueError("Numerator and denominator must be set")
    return ScipyDistribution(
      nominal=self.numerator,
      scipydistribution=scipy.stats.poisson(mu=self.numerator),
      unique_id=self.unique_id_numerator,
    ) / self.denominator

  def patient_nll(self, time, censored) -> KaplanMeierPatientNLL:
    """
    Get the patient NLL for the likelihood method.
    """
    if self.numerator is None or self.denominator is None:
      raise ValueError("Numerator and denominator must be set")
    return KaplanMeierPatientNLL.from_poisson_density(
      numerator_count=self.numerator,
      denominator_area=self.denominator,
      time=time,
      censored=censored,
    )

class PoissonRatioObservable(Observable):
  """
  A class to represent a ratio of two Poisson observables.

  This class is used to create a ratio of two Poisson distributions,
  which is useful for modeling the ratio of two counts.
  The numerator and denominator are specified as integers, and the
  unique IDs are used to identify the distributions in the datacard.

  Parameters:
  -----------
  numerator (int): The count for the numerator.
  denominator (int): The count for the denominator.
  unique_id_numerator (int): A unique ID for the numerator distribution.
  unique_id_denominator (int): A unique ID for the denominator distribution.
  """
  def __init__(
    self,
    *,
    numerator: int | None = None,
    denominator: int | None = None,
    unique_id_numerator: int,
    unique_id_denominator: int
  ):
    self.__numerator = None
    self.__denominator = None
    self.numerator = numerator
    self.denominator = denominator
    self.unique_id_numerator = unique_id_numerator
    self.unique_id_denominator = unique_id_denominator

    if not isinstance(unique_id_numerator, int):
      raise ValueError(f"Invalid unique_id_numerator: {unique_id_numerator}")
    if not isinstance(unique_id_denominator, int):
      raise ValueError(f"Invalid unique_id_denominator: {unique_id_denominator}")


  def __repr__(self):
    return f"{type(self).__name__}(numerator={self.numerator}, denominator={self.denominator})"

  @property
  def numerator(self):
    """
    Get the count for the numerator.
    """
    return self.__numerator
  @numerator.setter
  def numerator(self, value):
    if value is None:
      return
    if not isinstance(value, int) or value < 0:
      raise ValueError(f"Invalid numerator: {value}")
    if self.__numerator is not None and self.__numerator != value:
      raise ValueError("Numerator already set")
    self.__numerator = value
  @property
  def denominator(self):
    """
    Get the count for the denominator.
    """
    return self.__denominator
  @denominator.setter
  def denominator(self, value):
    if value is None:
      return
    if not isinstance(value, int) or value < 0:
      raise ValueError(f"Invalid denominator: {value}")
    if self.__denominator is not None and self.__denominator != value:
      raise ValueError("Denominator already set")
    self.__denominator = value

  def _create_observable_distribution(self):
    """
    Get the observable distribution for a ratio of two Poisson observables.
    """
    if self.numerator is None or self.denominator is None:
      raise ValueError("Numerator and denominator must be set")
    return ScipyDistribution(
      nominal=self.numerator,
      scipydistribution=scipy.stats.poisson(mu=self.numerator),
      unique_id=self.unique_id_numerator,
    ) / ScipyDistribution(
      nominal=self.denominator,
      scipydistribution=scipy.stats.poisson(mu=self.denominator),
      unique_id=self.unique_id_denominator,
    )

  def patient_nll(self, time, censored) -> KaplanMeierPatientNLL:
    """
    Get the patient NLL for the likelihood method.
    """
    if self.numerator is None or self.denominator is None:
      raise ValueError("Numerator and denominator must be set")
    return KaplanMeierPatientNLL.from_poisson_ratio(
      numerator_count=self.numerator,
      denominator_count=self.denominator,
      time=time,
      censored=censored,
    )


class Systematic:
  """
  A class to represent a systematic uncertainty.

  This class is used to apply systematic uncertainties to the observable
  distributions. The systematic type is specified as a string, and the
  unique ID is used to identify the systematic in the datacard.
  The only supported systematic type is "lnN", which represents a
  log-normal distribution.

  Parameters:
  name (str): The name of the systematic.
  systematic_type (str): The type of the systematic. Currently, only "lnN" is supported.
  unique_id (int): A unique ID for the systematic.
  """
  def __init__(self, name, systematic_type: str, unique_id: int):
    self.name = name
    if systematic_type not in ["lnN"]:
      raise ValueError(f"Invalid systematic type: {systematic_type}")
    self.systematic_type = systematic_type
    self.unique_id = unique_id

  def __repr__(self):
    return (
      f"Systematic(name={self.name}, systematic_type={self.systematic_type}, "
      f"unique_id={self.unique_id})"
    )

  @functools.cached_property
  def random_distribution(self):
    """
    Generate a random distribution for the systematic.
    """
    if self.systematic_type == "lnN":
      return ScipyDistribution(
        nominal=0,
        scipydistribution=scipy.stats.norm(),
        unique_id=self.unique_id
      )
    raise ValueError(f"Invalid systematic type: {self.systematic_type}")

  def apply(self, nominal, value):
    """
    Apply the systematic to a nominal value.
    """
    if self.systematic_type == "lnN":
      return nominal * value ** self.random_distribution
    raise ValueError(f"Invalid systematic type: {self.systematic_type}")

  def __eq__(self, other):
    if not isinstance(other, Systematic):
      return NotImplemented
    if self.name == other.name:
      if self.unique_id != other.unique_id:
        raise ValueError(
          f"Systematic {self.name} has different unique IDs: "
          f"{self.unique_id} and {other.unique_id}"
        )
      if self.systematic_type != other.systematic_type:
        raise ValueError(
          f"Systematic {self.name} has different types: "
          f"{self.systematic_type} and {other.systematic_type}"
        )
      return True
    return False

class Patient: # pylint: disable=too-many-instance-attributes
  """
  A class to represent a patient.
  """
  def __init__( # pylint: disable=too-many-arguments
    self,
    *,
    response: Response | None = None,
    survival_time: float | None = None,
    censored: bool | None = None,
    observable: Observable | None = None,
    systematics: list[tuple[Systematic, float]] | None = None,
  ):
    self.__response = None
    self.__survival_time = None
    self.__censored = None
    self.__observable = None
    self.__systematics = []
    self.response = response
    self.survival_time = survival_time
    self.censored = censored
    self.observable = observable
    if systematics is None:
      systematics = []
    for systematic, value in systematics:
      self.add_systematic(systematic, value)

  def __repr__(self):
    return f"Patient(response={self.response}, observable={self.observable})"

  @property
  def response(self):
    """
    Get the response for the patient.
    """
    return self.__response
  @response.setter
  def response(self, value):
    if value is not None and not isinstance(value, Response):
      raise ValueError(f"Invalid response: {value}")
    if self.__response is not None:
      raise ValueError("Response already set")
    self.__response = value
  @property
  def is_responder(self):
    """
    Check if the patient is a responder.
    """
    if self.response is None:
      raise ValueError("Response not set")
    return {
      "responder": True,
      "non-responder": False,
    }[self.response.response]

  @property
  def survival_time(self):
    """
    Get the survival time for the patient.
    """
    return self.__survival_time
  @survival_time.setter
  def survival_time(self, value):
    if value is not None and not isinstance(value, (int, float)):
      raise ValueError(f"Invalid survival time: {value}")
    if self.__survival_time is not None:
      raise ValueError("Survival time already set")
    self.__survival_time = value

  @property
  def censored(self):
    """
    Get the censored status for the patient.
    """
    return self.__censored
  @censored.setter
  def censored(self, value):
    if value is not None and not isinstance(value, bool):
      raise ValueError(f"Invalid censored status: {value}")
    if self.__censored is not None:
      raise ValueError("Censored status already set")
    self.__censored = value

  @property
  def observable(self):
    """
    Get the observable for the patient.
    """
    return self.__observable
  @observable.setter
  def observable(self, value):
    if value is not None and not isinstance(value, Observable):
      raise ValueError(f"Invalid observable: {value}")
    if self.__observable is not None:
      if (
        isinstance(value, PoissonRatioObservable)
        and isinstance(self.__observable, PoissonRatioObservable)
      ):
        self.__observable.numerator = value.numerator
        self.__observable.denominator = value.denominator
      elif (
        isinstance(value, PoissonDensityObservable)
        and isinstance(self.__observable, PoissonDensityObservable)
      ):
        self.__observable.numerator = value.numerator
        self.__observable.denominator = value.denominator
      else:
        raise ValueError("Observable already set")
    else:
      self.__observable = value

  @property
  def systematics(self):
    """
    Get the systematics for the patient.
    """
    return self.__systematics

  def add_systematic(self, systematic: Systematic, value: float):
    """
    Add a systematic to the patient.
    """
    for s, v in self.__systematics:
      if s == systematic:
        raise ValueError(f"Systematic {systematic} already added with value {v}")
    self.__systematics.append((systematic, value))

  def get_distribution(self) -> DistributionBase:
    """
    Get the distribution for the patient.
    """
    if self.observable is None:
      raise ValueError("Observable not set")
    result = self.observable.observable_distribution
    for systematic, value in self.__systematics:
      if value is not None:
        result = systematic.apply(result, value)
    return result

  def get_nll(self) -> KaplanMeierPatientNLL:
    """
    Get the NLL for the patient.
    """
    if self.observable is None:
      raise ValueError("Observable not set")
    if self.survival_time is None:
      raise ValueError("Survival time not set")
    if self.censored is None:
      raise ValueError("Censored status not set")
    result = self.observable.patient_nll(self.survival_time, self.censored)
    for systematic, value in self.__systematics: # pylint: disable=unused-variable
      raise NotImplementedError(
        "Systematics for KaplanMeierPatientNLL not implemented yet"
      )
      # result = systematic.apply(result, value)
    return result

class Datacard:
  """
  A datacard class to specify the inputs to ROC Picker.
  Refer to docs/03_examples.md for usage examples.
  """
  def __init__(self, patients: list[Patient]):
    """
    Initialize a datacard.
    This function should not be called directly. Use `parse_datacard` instead.
    """
    self.__patients = patients

  @property
  def patients(self):
    """
    Get the patients in the datacard.
    """
    return self.__patients

  @property
  def observable_type(self):
    """
    Get the observable type for the datacard.
    """
    if not self.__patients:
      raise ValueError("No patients found")
    observable_types = {type(p.observable) for p in self.__patients}
    if len(observable_types) != 1:
      raise ValueError("Mismatched observable types")
    result, = observable_types
    return result

  @property
  def systematics(self):
    """
    Get the systematics for the datacard.
    """
    systematics = set()
    for p in self.__patients:
      for systematic, _ in p.systematics:
        systematics.add(systematic)
    return systematics

  @classmethod
  def parse_datacard(cls, file_path): # pylint: disable=too-many-branches, too-many-statements, too-many-locals
    #disable warnings because this function is just parsing a file and is not too complex
    """
    Parse a datacard file and return a Datacard object.

    Parameters:
    file_path (os.PathLike): Path to the datacard file.
    """
    with open(file_path, 'r', encoding='utf-8') as file:
      lines = file.readlines()

    observable_type = None
    patients = None

    unique_id_generator = itertools.count(0)

    for line in lines:
      line = line.strip()
      if not line or line.startswith('#') or line.startswith('---'):
        continue

      split = line.split()
      if split[0] == "observable_type":
        observable_type = split[1]
        if observable_type not in ["fixed", "poisson", "poisson_density", "poisson_ratio"]:
          raise ValueError(f"Invalid observable_type: {observable_type}")
      elif split[0] == "bin":
        pass
      elif split[0] in ["response", "survival_time"]:
        if patients is not None:
          raise ValueError("Multiple 'response' lines found")
        patients = cls.process_response_line(
          split=split,
        )
      elif split[0] == "censored":
        if patients is None:
          raise ValueError("No 'response' line found before 'censored' line")
        if len(split) != len(patients) + 1:
          raise ValueError(
            f"Number of censored values ({len(split) - 1}) "
            f"does not match number of patients ({len(patients)})"
          )
        for patient, censored in zip(patients, split[1:], strict=True):
          patient.censored = {
            0: False,
            1: True,
          }[int(censored)]
      elif split[0] in ["observable", "count", "num", "denom", "area"]:
        if observable_type is None:
          raise ValueError(f"No 'observable_type' line found before '{split[0]}' line")
        if patients is None:
          raise ValueError(f"No 'response' line found before '{split[0]}' line")

        observables = cls.process_observable_line(
          split=split,
          observable_type=observable_type,
          unique_id_generator=(
            unique_id_generator
            if patients[0].observable is None #pylint: disable=unsubscriptable-object
            #if the observable is already set, then the new Observable
            #object is not used and so we just use a dummy.
            else itertools.count(0)
          ),
        )
        if len(observables) != len(patients):
          raise ValueError(
            f"Number of {split[0]} values ({len(observables)}) "
            f"does not match number of patients ({len(patients)})"
          )
        for patient, observable in zip(patients, observables, strict=True):
          patient.observable = observable
      elif split[1] in ["lnN"]:
        if observable_type is None:
          raise ValueError(f"No 'observable_type' line found before '{split[0]}' line")
        if patients is None:
          raise ValueError(f"No 'response' line found before '{split[0]}' line")
        systematic, systematic_values = cls.process_systematic_line(
          split=split,
          unique_id_generator=unique_id_generator,
        )
        if len(systematic_values) != len(patients):
          raise ValueError(
            f"Number of systematic values ({len(systematic_values)}) "
            f"does not match number of patients ({len(patients)})"
          )
        for patient, value in zip(patients, systematic_values, strict=True):
          if value is not None:
            patient.add_systematic(systematic, value)
      else:
        raise ValueError(f"Unexpected line format: {line}")

    if observable_type is None:
      raise ValueError("No 'observable_type' line found")
    if patients is None:
      raise ValueError("No 'response' line found")
    return Datacard(
      patients=patients,
    )

  @classmethod
  def process_response_line(cls, split: list[str]):
    """
    Process a line of the datacard that specifies responses.
    This function is used to create the appropriate response objects.
    """
    if len(split) < 2:
      raise ValueError(f"Invalid response line: {split}")
    if split[0] == "response":
      responses = [Response(response) for response in split[1:]]
      patients = [Patient(response=response) for response in responses]
    elif split[0] == "survival_time":
      survival_times = [float(x) for x in split[1:]]
      patients = [Patient(survival_time=survival_time) for survival_time in survival_times]
    else:
      raise ValueError(f"Invalid response line: {split}")
    return patients

  @classmethod
  def process_observable_line(
    cls,
    *,
    split: list[str],
    observable_type: str,
    unique_id_generator: itertools.count
  ):
    """
    Process a line of the datacard that specifies observables.
    This function is used to create the appropriate observable objects.
    """
    if (observable_type, split[0]) not in (
      ("fixed", "observable"),
      ("poisson", "count"),
      ("poisson_density", "num"),
      ("poisson_density", "area"),
      ("poisson_ratio", "num"),
      ("poisson_ratio", "denom"),
    ):
      raise ValueError(
        f"Unexpected '{split[0]}' line for observable_type '{observable_type}'"
      )
    value_type = {
      ("fixed", "observable"): float,
      ("poisson", "count"): int,
      ("poisson_density", "num"): int,
      ("poisson_density", "area"): float,
      ("poisson_ratio", "num"): int,
      ("poisson_ratio", "denom"): int,
    }[observable_type, split[0]]
    values = [value_type(_) for _ in split[1:]]

    if observable_type == "fixed":
      observables = [FixedObservable(value) for value in values]
    elif observable_type == "poisson":
      observables = [
        PoissonObservable(
          value,
          unique_id=next(unique_id_generator)
        ) for value in values
      ]
    elif observable_type == "poisson_density":
      kw = {"num": "numerator", "area": "denominator"}[split[0]]
      observables = [
        PoissonDensityObservable(
          **{
            kw: value,
            "unique_id_numerator": next(unique_id_generator),
          },
        )
        for value in values
      ]
    elif observable_type == "poisson_ratio":
      kw = {"num": "numerator", "denom": "denominator"}[split[0]]
      observables = [
        PoissonRatioObservable(
          **{
            kw: value,
          },
          unique_id_numerator=next(unique_id_generator),
          unique_id_denominator=next(unique_id_generator),
        )
        for value in values
      ]
    else:
      assert False, f"Unexpected observable_type: {observable_type}"

    return observables

  @classmethod
  def process_systematic_line(
    cls,
    *,
    split: list[str],
    unique_id_generator: itertools.count,
  ):
    """
    Process a line of the datacard that specifies systematics.
    This function is used to create the appropriate systematic objects.
    """
    systematic_name = split[0]
    systematic_type = split[1]
    systematic_values = [float(x) if x != '-' else None for x in split[2:]]
    systematic = Systematic(
      name=systematic_name,
      systematic_type=systematic_type,
      unique_id=next(unique_id_generator),
    )
    return systematic, systematic_values


  def systematics_mc_roc(self, *, flip_sign=False):
    """
    Generate a set of ROCDistributions for generating ROC curve
    error bands using the MC method.  See docs/02_rocpicker.tex for
    math details and docs/03_examples.md for usage examples.
    """

    responders = [
      p.get_distribution()
      for p in self.patients
      if p.is_responder
    ]
    nonresponders = [
      p.get_distribution()
      for p in self.patients
      if not p.is_responder
    ]

    return ROCDistributions(responders=responders, nonresponders=nonresponders, flip_sign=flip_sign)

  def discrete_roc(self, **kwargs):
    """
    Generate a DiscreteROC object for the discrete method.
    See docs/02_rocpicker.tex for math details and docs/03_examples.md
    for usage examples.
    """
    if self.observable_type != FixedObservable:
      raise ValueError(f"Invalid observable_type {self.observable_type} for discrete")
    if self.systematics:
      raise ValueError("Can't do systematics for discrete")

    responders: list[float] = []
    nonresponders: list[float] = []
    dct = {
      True: responders,
      False: nonresponders,
    }
    for p in self.patients:
      if not isinstance(p.observable, FixedObservable):
        raise ValueError(f"Invalid observable type {type(p.observable)} for discrete")
      distribution = p.get_distribution()
      if not isinstance(distribution, DummyDistribution):
        assert False
      dct[p.is_responder].append(float(distribution))

    return DiscreteROC(responders=responders, nonresponders=nonresponders, **kwargs)

  def delta_functions_roc(self, **kwargs):
    """
    Generate a DeltaFunctions object for the delta_functions method.
    See docs/02_rocpicker.tex for math details and docs/03_examples.md
    for usage examples.
    """
    if self.observable_type != FixedObservable:
      raise ValueError(f"Invalid observable_type {self.observable_type} for discrete")
    if self.systematics:
      raise ValueError("Can't do systematics for discrete")

    responders: list[float] = []
    nonresponders: list[float] = []
    dct = {
      True: responders,
      False: nonresponders,
    }
    for p in self.patients:
      if not isinstance(p.observable, FixedObservable):
        raise ValueError(f"Invalid observable type {type(p.observable)} for discrete")
      distribution = p.get_distribution()
      if not isinstance(distribution, DummyDistribution):
        assert False
      dct[p.is_responder].append(distribution.nominal)

    return DeltaFunctionsROC(responders=responders, nonresponders=nonresponders, **kwargs)

  def km_likelihood(
    self,
    parameter_min: float,
    parameter_max: float,
    *,
    endpoint_epsilon: float = 1e-6,
  ) -> KaplanMeierLikelihood:
    """
    Generate a KaplanMeierLikelihood object for generating Kaplan-Meier
    error bands using the likelihood method.
    """
    patients = []
    for p in self.patients:
      nll = p.get_nll()
      patients.append(nll)
    return KaplanMeierLikelihood(
      all_patients=patients,
      parameter_min=parameter_min,
      parameter_max=parameter_max,
      endpoint_epsilon=endpoint_epsilon,
    )

  def clear_distributions(self):
    """
    Delete the distributions for all patients.
    This is useful for clearing the unique_ids so that they can be
    regenerated.  You can always rerun systematics_mc_roc() or
    systematics_mc_km() to regenerate the distributions.
    """
    for p in self.patients:
      if p.observable is not None:
        del p.observable.observable_distribution

def plot_systematics_mc_roc():
  """
  Run MC method from a datacard.
  """
  # pylint: disable=C0301
  parser = argparse.ArgumentParser(description="Run MC method from a datacard.")
  parser.add_argument("datacard", type=pathlib.Path, help="Path to the datacard file.")
  parser.add_argument("output_file", type=pathlib.Path, help="Path to the output file for the plot.")
  parser.add_argument("--nrocs", type=int, help="Number of MC samples to generate.", default=10000, dest="size")
  parser.add_argument("--random-seed", type=int, help="Random seed for generation", dest="random_state", default=123456)
  parser.add_argument("--flip-sign", action="store_true", help="flip the sign of the observable (use this if AUC is < 0.5 and you want it to be > 0.5)")
  # pylint: enable=C0301

  args = parser.parse_args()
  datacard = Datacard.parse_datacard(args.__dict__.pop("datacard"))
  rd = datacard.systematics_mc_roc(flip_sign=args.__dict__.pop("flip_sign"))
  rocs = rd.generate(size=args.__dict__.pop("size"), random_state=args.__dict__.pop("random_state"))
  rocs.plot(saveas=args.__dict__.pop("output_file"))
  if args.__dict__:
    raise ValueError(f"Unused arguments: {args.__dict__}")

def plot_discrete_roc():
  """
  Run discrete method from a datacard.
  """
  # pylint: disable=C0301
  parser = argparse.ArgumentParser(description="Run discrete method from a datacard.")
  parser.add_argument("datacard", type=pathlib.Path, help="Path to the datacard file.")
  parser.add_argument("--roc-filename", type=pathlib.Path, help="Path to the output file for the ROC curve.", dest="rocfilename")
  parser.add_argument("--roc-errors-filename", type=pathlib.Path, help="Path to the output file for the ROC curve with error bands.", dest="rocerrorsfilename")
  parser.add_argument("--scan-filename", type=pathlib.Path, help="Path to the output file for the likelihood scan", dest="scanfilename")
  parser.add_argument("--y-upper-limit", type=float, help="y axis upper limit of the likelihood scan plot", dest="yupperlim")
  parser.add_argument("--npoints", type=int, help="number of points in the likelihood scan", dest="npoints")
  parser.add_argument("--flip-sign", action="store_true", help="flip the sign of the observable (use this if AUC is < 0.5 and you want it to be > 0.5)")
  # pylint: enable=C0301

  args = parser.parse_args()
  datacard = Datacard.parse_datacard(args.__dict__.pop("datacard"))
  discrete = datacard.discrete_roc(flip_sign=args.__dict__.pop("flip_sign"))
  discrete.make_plots(
    filenames=[
      args.__dict__.pop("rocfilename"),
      args.__dict__.pop("scanfilename"),
      args.__dict__.pop("rocerrorsfilename"),
    ],
    yupperlim=args.__dict__.pop("yupperlim"),
    npoints=args.__dict__.pop("npoints"),
  )
  if args.__dict__:
    raise ValueError(f"Unused arguments: {args.__dict__}")

def plot_delta_functions_roc():
  """
  Run delta functions method from a datacard.
  """
  # pylint: disable=C0301
  parser = argparse.ArgumentParser(description="Run delta functions method from a datacard.")
  parser.add_argument("datacard", type=pathlib.Path, help="Path to the datacard file.")
  parser.add_argument("--roc-filename", type=pathlib.Path, help="Path to the output file for the ROC curve.", dest="rocfilename")
  parser.add_argument("--roc-errors-filename", type=pathlib.Path, help="Path to the output file for the ROC curve with error bands.", dest="rocerrorsfilename")
  parser.add_argument("--scan-filename", type=pathlib.Path, help="Path to the output file for the likelihood scan", dest="scanfilename")
  parser.add_argument("--y-upper-limit", type=float, help="y axis upper limit of the likelihood scan plot", dest="yupperlim")
  parser.add_argument("--npoints", type=int, help="number of points in the likelihood scan", dest="npoints")
  parser.add_argument("--flip-sign", action="store_true", help="flip the sign of the observable (use this if AUC is < 0.5 and you want it to be > 0.5)")
  # pylint: enable=C0301

  args = parser.parse_args()
  datacard = Datacard.parse_datacard(args.__dict__.pop("datacard"))
  deltafunctions = datacard.delta_functions_roc(flip_sign=args.__dict__.pop("flip_sign"))
  deltafunctions.make_plots(
    filenames=[
      args.__dict__.pop("rocfilename"),
      args.__dict__.pop("scanfilename"),
      args.__dict__.pop("rocerrorsfilename"),
    ],
    yupperlim=args.__dict__.pop("yupperlim"),
    npoints=args.__dict__.pop("npoints"),
  )
  if args.__dict__:
    raise ValueError(f"Unused arguments: {args.__dict__}")

def plot_km_likelihood():
  """
  Run Kaplan-Meier likelihood method from a datacard.
  """
  # pylint: disable=C0301
  parser = argparse.ArgumentParser(description="Run Kaplan-Meier likelihood method from a datacard.")
  parser.add_argument("datacard", type=pathlib.Path, help="Path to the datacard file.")
  parser.add_argument("output_file", type=pathlib.Path, help="Path to the output file for the plot.")
  parser.add_argument("--parameter-min", type=float, help="Minimum parameter value for the likelihood scan.", dest="parameter_min", default=-np.inf)
  parser.add_argument("--parameter-max", type=float, help="Maximum parameter value for the likelihood scan.", dest="parameter_max", default=np.inf)
  group = parser.add_mutually_exclusive_group()
  group.add_argument("--include-binomial-only", action="store_true", help="Include error bands for the binomial error alone.")
  group.add_argument("--include-patient-wise-only", action="store_true", help="Include error bands for the patient-wise error alone.")
  parser.add_argument("--exclude-full-nll", action="store_false", help="Exclude the full NLL from the plot.", dest="include_full_NLL", default=True)
  parser.add_argument("--include-median-survival", action="store_true", help="Include the median survival line in the plot.", dest="include_median_survival")
  # pylint: enable=C0301
  args = parser.parse_args()
  if (
    not args.include_full_NLL
    and not args.include_binomial_only
    and not args.include_patient_wise_only
  ):
    parser.error(
      "If --exclude-full-nll is set, at least one of "
      "--include-binomial-only or --include-patient-wise-only must be set."
    )
  datacard = Datacard.parse_datacard(args.__dict__.pop("datacard"))
  kml = datacard.km_likelihood(
    parameter_min=args.__dict__.pop("parameter_min"),
    parameter_max=args.__dict__.pop("parameter_max"),
  )

  # Create KaplanMeierPlotConfig object from parsed arguments
  plot_config = KaplanMeierPlotConfig(
    include_binomial_only=args.__dict__.pop("include_binomial_only"),
    include_patient_wise_only=args.__dict__.pop("include_patient_wise_only"),
    include_full_NLL=args.__dict__.pop("include_full_NLL"),
    include_median_survival=args.__dict__.pop("include_median_survival"),
    saveas=args.__dict__.pop("output_file"),
  )

  kml.plot(config=plot_config)

  if args.__dict__:
    raise ValueError(f"Unused arguments: {args.__dict__}")

def plot_km_likelihood_two_groups():
  """
  Run Kaplan-Meier likelihood method from a datacard, and plot Kaplan-Meier
  curves for two groups separated into high and low values of the parameter.
  """
  # pylint: disable=C0301
  parser = argparse.ArgumentParser(description="Run Kaplan-Meier likelihood method from a datacard, and plot Kaplan-Meier curves for two groups separated into high and low values of the parameter.")
  parser.add_argument("datacard", type=pathlib.Path, help="Path to the datacard file.")
  parser.add_argument("output_file", type=pathlib.Path, help="Path to the output file for the plot.")
  parser.add_argument("--parameter-threshold", type=float, help="Threshold value for the parameter to separate the two groups.", dest="parameter_threshold", required=True)
  group = parser.add_mutually_exclusive_group()
  group.add_argument("--include-binomial-only", action="store_true", help="Include error bands for the binomial error alone.")
  group.add_argument("--include-patient-wise-only", action="store_true", help="Include error bands for the patient-wise error alone.")
  parser.add_argument("--exclude-full-nll", action="store_false", help="Exclude the full NLL from the plot.", dest="include_full_NLL", default=True)
  parser.add_argument("--include-median-survival", action="store_true", help="Include the median survival line in the plot.", dest="include_median_survival", default=True)
  # pylint: enable=C0301
  args = parser.parse_args()
  if (
    not args.include_full_NLL
    and not args.include_binomial_only
    and not args.include_patient_wise_only
  ):
    parser.error(
      "If --exclude-full-nll is set, at least one of "
      "--include-binomial-only or --include-patient-wise-only must be set."
    )
  datacard = Datacard.parse_datacard(args.__dict__.pop("datacard"))
  threshold = args.__dict__.pop("parameter_threshold")
  kml_low = datacard.km_likelihood(
    parameter_min=-np.inf,
    parameter_max=threshold,
  )
  kml_high = datacard.km_likelihood(
    parameter_min=threshold,
    parameter_max=np.inf,
  )

  # Common plot configuration arguments
  common_plot_kwargs = {
    "include_patient_wise_only": args.__dict__.pop("include_patient_wise_only"),
    "include_binomial_only": args.__dict__.pop("include_binomial_only"),
    "include_full_NLL": args.__dict__.pop("include_full_NLL"),
    "include_best_fit": False, # Explicitly set to False as per original logic
    "include_median_survival": args.__dict__.pop("include_median_survival"),
  }

  # Configuration for the 'High' group plot (creates the figure)
  config_high = KaplanMeierPlotConfig(
    **common_plot_kwargs,
    create_figure=True,
    close_figure=False, # Do not close figure after first plot
    show=False, # Do not show figure yet
    saveas=None, # Do not save yet
    nominal_label=f"High (n={len(kml_high.nominalkm.patients)})",
    nominal_color="blue",
    CL_colors=["dodgerblue", "skyblue"],
    title="Kaplan-Meier Curves", # Set title on the first plot config
    xlabel="Time", # Set xlabel on the first plot config
    ylabel="Survival Probability", # Set ylabel on the first plot config
    show_grid=True, # Set show_grid on the first plot config
  )
  kml_high.plot(config=config_high)

  # Configuration for the 'Low' group plot (draws on existing figure)
  config_low = KaplanMeierPlotConfig(
    **common_plot_kwargs,
    create_figure=False, # Do not create a new figure
    show=False, # Do not show figure yet, handled by saveas
    saveas=args.__dict__.pop("output_file"), # Save the combined plot here
    nominal_label=f"Low (n={len(kml_low.nominalkm.patients)})",
    nominal_color="red",
    CL_colors=["orangered", "lightcoral"],
    # Title, labels, grid are already set by config_high, but can be overridden here if needed
    # For a combined plot, it's better to set them once.
    title="Kaplan-Meier Curves", # Re-setting for clarity, but already set by config_high
    xlabel="Time",
    ylabel="Survival Probability",
    show_grid=True,
  )
  kml_low.plot(config=config_low)

  if args.__dict__:
    raise ValueError(f"Unused arguments: {args.__dict__}")
