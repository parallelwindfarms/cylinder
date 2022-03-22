# ~\~ language=Python filename=pintFoam/parareal/harmonic_oscillator.py
# ~\~ begin <<lit/parareal.md|pintFoam/parareal/harmonic_oscillator.py>>[0]
from .abstract import (Problem)
from typing import Callable
from numpy.typing import NDArray
import numpy as np

def harmonic_oscillator(omega_0: float, zeta: float) -> Problem:
    def f(y, t):
        return np.r_[y[1], -2 * zeta * omega_0 * y[1] - omega_0**2 * y[0]]
    return f

# ~\~ begin <<lit/parareal.md|harmonic-oscillator-solution>>[0]
def underdamped_solution(omega_0: float, zeta: float) \
        -> Callable[[NDArray[np.float64]], NDArray[np.float64]]:
    amp   = 1 / np.sqrt(1 - zeta**2)
    phase = np.arcsin(zeta)
    freq  = omega_0 * np.sqrt(1 - zeta**2)

    def f(t):
        dampening = np.exp(-omega_0*zeta*t)
        q = amp * dampening * np.cos(freq * t - phase)
        p = - amp * omega_0 * dampening * np.sin(freq * t)
        return np.c_[q, p]
    return f
# ~\~ end
# ~\~ end
