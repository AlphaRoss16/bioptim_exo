from load_experimental_data import LoadData, C3dData
from scipy.integrate import solve_ivp
import numpy as np
import biorbd_casadi as biorbd
from casadi import MX, vertcat
from matplotlib import pyplot as plt
import os
from viz_tracking import add_custom_plots
from scipy.interpolate import interp1d
from datetime import datetime

from bioptim import (
    OptimalControlProgram,
    NonLinearProgram,
    BiMapping,
    DynamicsList,
    DynamicsFcn,
    DynamicsFunctions,
    ObjectiveList,
    ObjectiveFcn,
    InterpolationType,
    BoundsList,
    Bounds,
    QAndQDotBounds,
    InitialGuessList,
    OdeSolver,
    Node,
    Solver,
    CostType,
    PlotType,
)


def get_phase_time_shooting_numbers(data, dt):
    phase_time = data.c3d_data.get_time()
    number_shooting_points = []
    for time in phase_time:
        number_shooting_points.append(int(time / dt))
    return phase_time, number_shooting_points


def prepare_ocp(
    biorbd_model: biorbd.Model,
    final_time: float,
    n_shooting: int,
    markers_ref: np.ndarray,  # to check
    q_ref: list,
    qdot_ref: list,
    nb_threads: int,
    ode_solver: OdeSolver = OdeSolver.RK4(),
) -> OptimalControlProgram:
    """
    Prepare the ocp to solve

    Parameters
    ----------
    biorbd_model: biorbd.Model
        The loaded biorbd model
    final_time: float
        The time at final node
    n_shooting: int
        The number of shooting points
    markers_ref: np.ndarray
        The marker to track if 'markers' is chosen in kin_data_to_track
    q_ref: list
        List of the array of joint trajectories.
        Those trajectories were computed using Kalman filter
        They are used as initial guess
    qdot_ref: list
        List of the array of joint velocities.
        Those velocities were computed using Kalman filter
        They are used as initial guess
    nb_threads:int
        The number of threads used
    ode_solver: OdeSolver
        The ode solver to use

    Returns
    -------
    The OptimalControlProgram ready to solve
    """
    nb_q = biorbd_model.nbQ()
    nb_qdot = biorbd_model.nbQdot()

    # Add objective functions
    objective_functions = ObjectiveList()
    objective_functions.add(ObjectiveFcn.Lagrange.MINIMIZE_CONTROL, key="tau", weight=10)
    objective_functions.add(ObjectiveFcn.Mayer.TRACK_MARKERS, weight=100, target=markers_ref, node=Node.ALL)
    # todo add a if with_floating base
    objective_functions.add(ObjectiveFcn.Lagrange.MINIMIZE_STATE, weight=10, key="qdot", index=[0, 1, 2, 3, 4, 5])

    # Dynamics
    dynamics = DynamicsList()
    dynamics.add(DynamicsFcn.TORQUE_DRIVEN)

    # Path constraint
    x_bounds = BoundsList()
    x_bounds.add(bounds=QAndQDotBounds(biorbd_model))

    # Initial guess
    init_x = np.zeros((nb_q + nb_qdot, n_shooting + 1))
    init_x[:nb_q, :] = q_ref[0]
    init_x[nb_q: nb_q + nb_qdot, :] = qdot_ref[0]

    x_init = InitialGuessList()
    x_init.add(init_x, interpolation=InterpolationType.EACH_FRAME)

    # Define control path constraint
    u_bounds = BoundsList()
    u_init = InitialGuessList()
    tau_min, tau_max, tau_init = -100, 100, 0
    u_bounds.add(
        [tau_min] * biorbd_model.nbGeneralizedTorque(),
        [tau_max] * biorbd_model.nbGeneralizedTorque(),
    )
    u_init.add([tau_init] * biorbd_model.nbGeneralizedTorque())

    # ------------- #

    return OptimalControlProgram(
        biorbd_model=biorbd_model,
        dynamics=dynamics,
        n_shooting=n_shooting,
        phase_time=final_time,
        x_init=x_init,
        u_init=u_init,
        x_bounds=x_bounds,
        u_bounds=u_bounds,
        objective_functions=objective_functions,
        ode_solver=ode_solver,
    )


def main():
    """
    Get data, then create a tracking problem, and finally solve it and plot some relevant information
    """

    # Define the problem
    with_floating_base = True
    # c3d_path = "../data/F0_aisselle_05.c3d"
    c3d_path = "../data/F0_aisselle_05_crop.c3d"

    model_path = "../models/wu_converted_definitif.bioMod" if with_floating_base \
        else "../models/wu_converted_definitif_without_floating_base_and_thorax_markers.bioMod"

    q_file = os.path.splitext(c3d_path)[0] + "_q.txt"
    qdot_file = os.path.splitext(c3d_path)[0] + "_qdot.txt"

    biorbd_model = biorbd.Model(model_path)
    data = C3dData(c3d_path)

    final_time = data.get_final_time()
    # final_time = 0.3
    n_shooting_points = 50

    # Marker ref
    data_loaded = LoadData(biorbd_model, c3d_path, q_file, qdot_file)

    q_ref, qdot_ref, markers_ref = data_loaded.get_experimental_data([n_shooting_points],
                                                                     [final_time],
                                                                     with_floating_base=with_floating_base)

    ocp = prepare_ocp(
        biorbd_model=biorbd_model,
        final_time=final_time,
        n_shooting=n_shooting_points,
        markers_ref=markers_ref[0],
        q_ref=q_ref,
        qdot_ref=qdot_ref,
        nb_threads=8,
    )

    ocp.add_plot_penalty(CostType.ALL)
    ocp = add_custom_plots(ocp, 0, 19)

    # --- Solve the program --- #
    solver = Solver.IPOPT(show_online_optim=True, show_options=dict(show_bounds=True))
    solver.set_maximum_iterations(100)
    sol = ocp.solve(solver)

    # --- Save --- #
    save_path = f"{'save/tracking_task'} {datetime.now()}"
    # save_path = "custom_name"  # custom the name for the assay
    save_path = save_path.replace(" ", "_")
    save_path = save_path.replace("-", "_")
    save_path = save_path.replace(":", "_")
    save_path = save_path.replace(".", "_")
    ocp.save(sol, save_path)

    # --- Plot --- #
    sol.graphs(show_bounds=True)
    sol.animate(n_frames=100)

    # --- Show the results --- #
    q = sol.states["q"]
    n_q = ocp.nlp[0].model.nbQ()
    n_mark = ocp.nlp[0].model.nbMarkers()
    n_frames = q.shape[1]

    markers = np.ndarray((3, n_mark, q.shape[1]))
    symbolic_states = MX.sym("x", n_q, 1)
    markers_func = biorbd.to_casadi_func("ForwardKin", biorbd_model.markers, symbolic_states)
    for i in range(n_frames):
        markers[:, :, i] = markers_func(q[:, i])

    plt.figure("Markers")
    n_steps_ode = ocp.nlp[0].ode_solver.steps + 1 if ocp.nlp[0].ode_solver.is_direct_collocation else 1
    for i in range(markers.shape[1]):
        plt.plot(np.linspace(0, 2, n_shooting_points + 1), markers_ref[:, i, :].T, "k")
        plt.plot(np.linspace(0, 2, n_shooting_points * n_steps_ode + 1), markers[:, i, :].T, "r--")
    plt.xlabel("Time")
    plt.ylabel("Markers Position")

    plt.show()


if __name__ == "__main__":
    main()
