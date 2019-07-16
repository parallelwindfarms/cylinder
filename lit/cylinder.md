# PyFOAM

PyFOAM is not so well documented. For our application we'd like to do two things: modify the run-directory and run `icoFoam`. We'll start with the following modules:

- `PyFoam.Execution`
- `PyFoam.RunDictionary`
- `PyFoam.LogAnalysis`

The PyFAOM module comes with a lot of tools to analyse the logs that are being created so fanatically by the solvers.

## Running `elbow` example

To run the "elbow" example:

``` {.python #elbow-example}
from PyFoam.Execution.AnalyzedRunner import AnalyzedRunner
from PyFoam.LogAnalysis.StandardLogAnalyzer import StandardLogAnalyzer
```

The `AnalyzedRunner` runs a command and sends the results to an `Analyzer` object, all found in the `PyFoam.LogAnalysis` module, in this case the `StandardLogAnalyzer`.

``` {.python session=0}
import numpy as np
from pathlib import Path
from pintFoam.utils import pushd

path = Path("./elbow").absolute()
solver = "icoFoam"

with pushd(path):
    run = AnalyzedRunner(StandardLogAnalyzer(), argv=[solver], silent=True)
    run.start()
```

### Get results

All access to files goes through the `PyFoam.RunDictionary` submodule.

``` {.python session=0}
from PyFoam.RunDictionary.SolutionDirectory import SolutionDirectory
dire = SolutionDirectory(path)
```

Query for the time slices,

``` {.python session=0}
dire.times
```

And read some result data,

``` {.python session=0 clip-output=4}
p = dire[10]['p'].getContent()['internalField']
np.array(p.val)
```

### Clear results

``` {.python session=0}
dire.clearResults()
```

### Change integration interval and time step

We'll now access the `controlDict` file.

``` {.python session=0}
from PyFoam.RunDictionary.ParsedParameterFile import ParsedParameterFile
controlDict = ParsedParameterFile(dire.controlDict())
controlDict.content
```

change the end time

``` {.python session=0}
controlDict['endTime'] = 20
controlDict.writeFile()
```

# Interface with ParaNoodles

We need to define the following:

* `Vector`
* fine `Solution`
* coarse `Solution`
* coarsening operator
* refinement operator (interpolation)

The last two steps will require the use of the `mapFields` utility in OpenFOAM and may require some tweaking to work out.

## Vector

``` {.python file=pintFoam/vector.py}
from __future__ import annotations

import numpy as np
import operator

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4
from shutil import copytree, rmtree

from .utils import pushd

from PyFoam.RunDictionary.ParsedParameterFile import ParsedParameterFile
from PyFoam.RunDictionary.SolutionDirectory import SolutionDirectory
from PyFoam.Execution.UtilityRunner import UtilityRunner

<<base-case>>
<<pintfoam-vector>>
<<pintfoam-set-fields>>
```

The abstract `Vector` representing any single state in the simulation consists of a `RunDirectory` and a time-frame.


### Base case
We will operate on a `Vector`, the same way everything is done in OpenFOAM. Copy, paste and edit. This is why for every `Vector` we define a `BaseCase` that is used to generate new vectors. The `BaseCase` should have only one time directory, namely `0`.

``` {.python #base-case}
@dataclass
class BaseCase:
    """Base case is a cleaned version of the system. If it contains any fields,
    it will only be the `0` time. Any field that is copied for manipulation will
    do so on top of an available base case in the `0` slot."""
    root: Path
    case: str

    @property
    def path(self):
        return self.root / self.case

    def new_vector(self, name=None):
        """Creates new `Vector` using this base case."""
        new_case = name or uuid4().hex
        new_path = self.root / new_case
        if not new_path.exists():
            copytree(self.path, new_path)
        return Vector(self, new_case, "0")

    def all_vector_paths(self):
        """Iterates all sub-directories in the root."""
        return (x for x in self.root.iterdir()
                if x.is_dir() and x.name != self.case)

    def clean(self):
        """Deletes all vectors of this base-case."""
        for path in self.all_vector_paths():
            rmtree(path)
```

If no name is given to a new vector, a random one is generated.

### Retrieving files and time directories
Note that the `BaseCase` has a property `path`. The same property will be defined in `Vector`. We can use this common property to retrieve a `SolutionDirectory`, `ParameterFile` or `TimeDirectory`.

``` {.python #pintfoam-vector}
def solution_directory(case):
    return SolutionDirectory(case.path)

def parameter_file(case, relative_path):
    return ParsedParameterFile(case.path / relative_path)

def time_directory(case):
    return solution_directory(case)[case.time]
```

### Vector

``` {.python #pintfoam-vector}
@dataclass
class Vector:
    base: BaseCase
    case: str
    time: str

    <<pintfoam-vector-properties>>
    <<pintfoam-vector-clone>>
    <<pintfoam-vector-operate>>
    <<pintfoam-vector-operators>>
```

From a vector we can extract a file path pointing to the specified time slot, list the containing files and read out `internalField` from any of those files.

``` {.python #pintfoam-vector-properties}
@property
def path(self):
    return self.base.root / self.case

@property
def files(self):
    return time_directory(self).getFiles()

def internalField(self, key):
    return np.array(time_directory(self)[key] \
        .getContent()['internalField'].val)
```

We clone a vector by creating a new vector and copying internal fields.

``` {.python #pintfoam-vector-clone}
def clone(self):
    x = self.base.new_vector()
    x.time = self.time
    rmtree(x.path/ x.time, ignore_errors=True)
    copytree(self.path / self.time, x.path / x.time)
    return x
```

Applying an operator to a vector follows a generic recipe:

``` {.python #pintfoam-vector-operate}
def _operate_vec_vec(self, other: Vector, op):
    x = self.clone()
    for f in self.files:
        b_f = other.internalField(f)
        x_f = x.internalField(f)
        x_content = time_directory(x)[f].getContent()

        if x_f.shape is ():
            x_content['internalField'].val = op(x_f, b_f)
        else:
            x_content['internalField'].val[:] = op(x_f, b_f)
        x_content.writeFile()
    return x

def _operate_vec_scalar(self, s: float, op):
    x = self.clone()
    for f in self.files:
        x_f = self.internalField(f)
        x_content = time_directory(x)[f].getContent()
        if x_f.shape is ():
            x_content['internalField'].val = op(x_f, s)
        else:
            x_content['internalField'].val[:] = op(x_f, s)
        x_content.writeFile()
    return x
```

We now have the tools to define vector addition, subtraction and scaling.

``` {.python #pintfoam-vector-operators}
def __sub__(self, other: Vector):
    return self._operate_vec_vec(other, operator.sub)

def __add__(self, other: Vector):
    return self._operate_vec_vec(other, operator.add)

def __mul__(self, scale: float):
    return self._operate_vec_scalar(scale, operator.mul)
```

### `setFields` utility

We may want to call `setFields` on our `Vector` to setup some test cases.

``` {.python #pintfoam-set-fields}
def setFields(v, *, defaultFieldValues, regions):
    x = parameter_file(v, "system/setFieldsDict")
    x['defaultFieldValues'] = defaultFieldValues
    x['regions'] = regions
    x.writeFile()

    with pushd(v.path):
        u = UtilityRunner(argv=['setFields'], silent=True)
        u.start()
```

## Solution

Remember, the definition of a `Solution`,

``` {.python #abstract-types}
Solution = Callable[[Vector, float, float], Vector]
```

meaning, we write a function taking a current state `Vector`, the time *now*, and the *target* time, returning a new `Vector`.

``` {.python file=pintFoam/solution.py}
from PyFoam.Execution.AnalyzedRunner import AnalyzedRunner
from PyFoam.LogAnalysis.StandardLogAnalyzer import StandardLogAnalyzer

from .vector import (Vector, parameter_file, solution_directory)
from .utils import pushd

<<pintfoam-epsilon>>
<<pintfoam-solution>>
```

The solver will write directories with floating-point valued names. This is a very bad idea by the folks at OpenFOAM, but it is one we'll have to live with. Suppose you have a time-step of $0.1$, what will be the names of the directories if you integrate from $0$ to $0.5$?

``` {.python session=0}
[x * 0.1 for x in range(6)]
```

In Python 3.7, this gives `[0.0, 0.1, 0.2, 0.30000000000000004, 0.4, 0.5]`. Surely, if you give a time-step of $0.1$ to OpenFOAM, it will create a directory named `0.3` instead. We'll define the constant `epsilon` to aid us in identifying the correct state directory given a floating-point time.

``` {.python #pintfoam-epsilon}
epsilon = 1e-6
```

Our solution depends on the solver chosen and the given time-step:

``` {.python #pintfoam-solution}
def foam(solver: str, dt: float, x: Vector, t_0: float, t_1: float):
    <<pintfoam-solution-function>>
```

The solver clones a new vector, sets the `controlDict`, runs the solver and then creates a new vector representing the last time slice.

``` {.python #pintfoam-solution-function}
assert abs(float(x.time) - t_0) < epsilon, f"Times should match: {t_0} != {x.time}."
y = x.clone()
<<set-control-dict>>
<<run-solver>>
<<return-result>>
```

### `controlDict`

``` {.python #set-control-dict}
controlDict = parameter_file(y, "system/controlDict")
controlDict.content['startTime'] = t_0
controlDict.content['endTime'] = t_1
controlDict.content['deltaT'] = dt
controlDict.content['writeInterval'] = dt
controlDict.writeFile()
```

### Run solver

``` {.python #run-solver}
with pushd(y.path):
    run = AnalyzedRunner(StandardLogAnalyzer(), argv=[solver], silent=True)
    run.start()
```

### Return result

``` {.python #return-result}
sd = solution_directory(y)
t1_str = sd.times[-1]
return Vector(y.base, y.case, t1_str)
```

# Running Parareal

``` {.python file=run.py}
import numpy as np

import noodles
from noodles.draw_workflow import draw_workflow
from noodles.run.threading.vanilla import run_parallel
from noodles.run.process import run_process
from noodles import serial
from paranoodles import tabulate, parareal

from pintFoam.vector import BaseCase
from pintFoam.run import (coarse, fine, registry)
from pathlib import Path


def paint(node, name):
    if name == "coarse":
        node.attr["fillcolor"] = "#cccccc"
    elif name == "fine":
        node.attr["fillcolor"] = "#88ff88"
    else:
        node.attr["fillcolor"] = "#ffffff"

if __name__ == "__main__":
    t = np.linspace(0.0, 1.0, 6)
    base_case = BaseCase(Path("data/c1").resolve(), "baseCase")

    y = noodles.gather(*tabulate(coarse, base_case.new_vector(), t))
    s = noodles.gather(*parareal(fine, coarse)(y, t))

    # draw_workflow("wf.svg", noodles.get_workflow(s), paint)
    result = run_process(s, n_processes=4, registry=registry)

    print(result)
# base_case.clean()
```

``` {.python file=pintFoam/run.py}
import noodles
from noodles import serial

from .solution import foam

@noodles.schedule
def fine(x, t_0, t_1):
    return foam("icoFoam", 0.05, x, t_0, t_1)

@noodles.schedule
def coarse(x, t_0, t_1):
    return foam("icoFoam", 0.2, x, t_0, t_1)

def registry():
    return serial.base() + serial.numpy()
```

# Appendix A: Utils

``` {.python file=pintFoam/utils.py}
<<push-dir>>
```

## Cleaning up

``` {.python file=pintFoam/clean.py}
import sys
from pathlib import Path
from .vector import BaseCase

if __name__ == "__main__":
    target = sys.argv[1]
    base_case = sys.argv[2]
    BaseCase(Path(target), base_case).clean()
```

## `pushd`

I haven't been able (with simple attempts) to run a case outside the definition directory. Similar to the `pushd` bash command, I define a little utility in Python:

``` {.python #push-dir}
import os
from pathlib import Path
from contextlib import contextmanager

@contextmanager
def pushd(path):
    """Context manager to change directory to given path,
    and get back to current dir at exit."""
    prev = Path.cwd()
    os.chdir(path)

    try:
        yield
    finally:
        os.chdir(prev)
```



