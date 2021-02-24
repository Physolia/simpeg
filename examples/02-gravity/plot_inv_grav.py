"""
PF: Gravity: Tiled Inversion Linear
===================================

Invert data in tiles.

"""
import numpy as np
import matplotlib.pyplot as plt

from dask.distributed import Client, LocalCluster
# from SimPEG.dask import data_misfit, objective_function
# from SimPEG.dask.utils import create_tile_meshes
from SimPEG.potential_fields import gravity
from SimPEG import (
    maps,
    data,
    regularization,
    optimization,
    inverse_problem,
    directives,
    inversion,
    data_misfit,
    objective_function,
)
from discretize.utils import mesh_builder_xyz, refine_tree_xyz

try:
    from SimPEG import utils
    from SimPEG.utils import plot2Ddata
except:
    from SimPEG import Utils as utils
    from SimPEG.Utils.Plotutils import plot2Ddata

import shutil
# Create and array of observation points
xr = np.linspace(-30.0, 30.0, 20)
yr = np.linspace(-30.0, 30.0, 20)
X, Y = np.meshgrid(xr, yr)

# Move the observation points 5m above the topo
Z = -np.exp((X ** 2 + Y ** 2) / 75 ** 2)

# Create a topo array
topo = np.c_[utils.mkvc(X.T), utils.mkvc(Y.T), utils.mkvc(Z.T)]

# Create station locations drapped 0.1 m above topo
rxLoc = np.c_[utils.mkvc(X.T), utils.mkvc(Y.T), utils.mkvc(Z.T) + 0.1]

# Setup a client with workers
cluster = LocalCluster(processes=False)
client = Client(cluster)
workers = None  # Here runs locally

##########################################################################
# Divided and Conquer
# -------------------
#
# Split the data set in two and create sub-problems
#
#

# Mesh parameters
h = [5, 5, 5]
padDist = np.ones((3, 2)) * 100

mesh = mesh_builder_xyz(
    rxLoc, h, padding_distance=padDist, depth_core=100, mesh_type="tree"
)
mesh = refine_tree_xyz(
    mesh, rxLoc, method="surface", octree_levels=[5, 5, 5], finalize=False
)
mesh = refine_tree_xyz(
    mesh, topo, method="surface", octree_levels=[0, 0, 2], finalize=True
)

# Define an active cells from topo
activeCells = utils.surface2ind_topo(mesh, topo)


##########################################################################
# Synthetic data simulation
# -------------------------
#
# We can now create a density model and generate data
# Here a simple block in half-space
# Get the indices of the magnetized block
model = np.zeros(mesh.nC)
ind = utils.ModelBuilder.getIndicesBlock(
    np.r_[-10, -10, -30], np.r_[10, 10, -10], mesh.gridCC,
)[0]

# Assign density values
model[ind] = 0.3

# Remove air cells
model = model[activeCells]

# Create reduced identity map
idenMap = maps.IdentityMap(nP=int(activeCells.sum()))

# Create a global survey just for simulation of data
receivers = gravity.receivers.Point(rxLoc)
srcField = gravity.sources.SourceField([receivers])
survey = gravity.survey.Survey(srcField)

# Create the forward simulation for the global dataset
simulation = gravity.simulation.Simulation3DIntegral(
    survey=survey, mesh=mesh, rhoMap=idenMap, actInd=activeCells
)

# Compute linear forward operator and compute some data
d = simulation.fields(model)

# Add noise and uncertainties
# We add some random Gaussian noise (1nT)
synthetic_data = d + np.random.randn(len(d)) * 1e-3
wd = np.ones(len(synthetic_data)) * 1e-3  # Assign flat uncertainties

data_object = data.Data(
    survey,
    dobs=synthetic_data,
    standard_deviation=wd,
)

global_misfit = data_misfit.L2DataMisfit(
            data=data_object, simulation=simulation,
)

# Create active map to go from reduce set to full
inject_global = maps.InjectActiveCells(mesh, activeCells, np.nan)

ax = plt.subplot()
mesh.plotSlice(inject_global * model, normal="Y", ax=ax, grid=True)
ax.scatter(rxLoc[:, 0], rxLoc[:, 2], 10, c='b')
ax.set_title(f"Global Mesh. Active cells {activeCells.sum()}")
ax.set_xlim(-60, 60)
ax.set_ylim(-50, 10)
ax.set_aspect("equal")
plt.show()


# Create a regularization on the global mesh
reg = regularization.Sparse(mesh, indActive=activeCells, mapping=idenMap)

m0 = np.ones(int(activeCells.sum())) * 1e-4  # Starting model

# Add directives to the inversion
opt = optimization.ProjectedGNCG(
    maxIter=100, lower=-1.0, upper=1.0, maxIterLS=20, maxIterCG=10, tolCG=1e-3
)
invProb = inverse_problem.BaseInvProblem(global_misfit, reg, opt)
betaest = directives.BetaEstimate_ByEig(beta0_ratio=1e-1)

# Here is where the norms are applied
# Use pick a threshold parameter empirically based on the distribution of
# model parameters
update_IRLS = directives.Update_IRLS(
    f_min_change=1e-4, max_irls_iterations=0, coolEpsFact=1.5, beta_tol=1e-2,
)
saveDict = directives.SaveOutputEveryIteration(save_txt=False)
update_Jacobi = directives.UpdatePreconditioner()
sensitivity_weights = directives.UpdateSensitivityWeights(everyIter=False)
inv = inversion.BaseInversion(
    invProb,
    directiveList=[update_IRLS, sensitivity_weights, betaest, update_Jacobi, saveDict],
)

# Run the inversion
mrec = inv.run(m0)


# Plot the result
ax = plt.subplot(1, 2, 1)
mesh.plotSlice(inject_global * model, normal="Y", ax=ax, grid=True)
ax.set_title("True")
ax.set_aspect("equal")

ax = plt.subplot(1, 2, 2)
mesh.plotSlice(inject_global * mrec, normal="Y", ax=ax, grid=True)
ax.set_title("Recovered")
ax.set_aspect("equal")
plt.show()