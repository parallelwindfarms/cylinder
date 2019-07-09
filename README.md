---
title: Flow past a cylinder and Parareal
author: Johan Hidding
---

Aim: simulate the turbulent flow past a cylinder in OpenFOAM and parallise with Parareal.

Steps:

1. Follow the [tutorial](https://wiki.openfoam.com/Vortex_shedding_by_Joel_Guerrero_2D) at [Wolf Dynamics](http://www.wolfdynamics.com/wiki/T5_2D_cylinder.pdf), supplementary material: [vortex_shedding.tar.gz](http://www.wolfdynamics.com/wiki/vortex_shedding.tar.gz).
2. Run tutorial straight from Python using pyFOAM.
3. Run parallel-in-time using Parareal in Python with Noodles.

![Flow around cylinder with Reynold's number 200.](./figures/case-result.png)

To install the requirements, also clone [ParaNoodles](https://github.com/ParallelWindfarms/paranoodles) and run `pip install .` from its project root. To install additional requirements, have OpenFOAM installed and:

```shell
pip install -r requirements.txt
```

## PyFOAM

PyFOAM is not so well documented. For our application we'd like to do two things: modify the run-directory and run `icoFoam`. We'll start with the following modules:

- `PyFoam.Execution`
- `PyFoam.RunDictionary`
- `PyFoam.LogAnalysis`

The PyFAOM module comes with a lot of tools to analyse the logs that are being created so fanatically by the solvers.

### Running `elbow` example

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
import numpy as np
import operator

from typing import NamedTuple
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
class BaseCase(NamedTuple):
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
        return Vector(self, new_case, 0)

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
class Vector(NamedTuple):
    base: BaseCase
    case: str
    time: int

    <<pintfoam-vector-properties>>
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
        .getContent().content['internalField'])
```

Applying an operator to a vector follows a generic recepy:

``` {.python #pintfoam-vector-operate}
def _operate_vec_vec(self, other: Vector, op):
    x = self.base.new_vector()
    for f in self.files:
        a_f = self.internalField(f)
        b_f = other.internalField(f)
        x_content = time_directory(x)[f].getContent()
        x_f = x_content.content['internalField'].val[:] = op(a_f, b_f)
        x_content.writeFile()
    return x

def _operate_vec_scalar(self, s: float, op):
    x = self.base.new_vector()
    for f in self.files:
        a_f = self.internalField(f)
        x_content = time_directory(x)[f].getContent()
        x_f = x_content.content['internalField'].val[:] = op(a_f, s)
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

# Appendix A: Utils

``` {.python file=pintFoam/utils.py}
<<push-dir>>
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




