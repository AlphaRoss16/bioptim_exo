import biorbd
from scipy import optimize
import numpy as np
import utils


def IK_Kinova(
        biorbd_model: biorbd.Model,
        markers_names: list[str],
        markers: np.ndarray,
        q0: np.ndarray,
        q_ik_1: np.ndarray,
        # table: np.ndarray,
        # thorax: np.ndarray
        ):
    """
    :param markers:
    :param markers_names:
    :param biorbd_model:
    :param table:
    :param thorax:
    :param q0:
    """
    def objective_function(x, biorbd_model, q_ik_thorax, table_markers, thorax_markers):
        markers_model = biorbd_model.markers(x)
        table5_xyz = np.linalg.norm(markers_model[markers_names.index('Table:Table5')].to_array()[:] - table_markers[:, 0]) ** 2
        table6_xy = np.linalg.norm(markers_model[markers_names.index('Table:Table6')].to_array()[:2] - table_markers[:2, 1]) ** 2
        mark_list = []
        mark_out = 0
        for j in range(len(thorax_markers[0, :])):
            mark = np.linalg.norm(markers_model[j].to_array()[:] - thorax_markers[:, j]) ** 2
            mark_list.append(mark)
            mark_out += mark

        T = biorbd_model.globalJCS(x, biorbd_model.nbSegment() - 1).to_array()
        out2 = T[2, 0] ** 2 + T[2, 1] ** 2 + T[0, 2] ** 2 + T[1, 2] ** 2 + (1 - T[2, 2]) ** 2

        out3 = 0
        for i, value in enumerate(q_ik_thorax):
            out3 += (x[i] - value) ** 2

        out4 = 0
        for h in range(1, 3):
            out4 += (x[-h] - 0.) ** 2

        return 1000 * table5_xyz + 1000 * table6_xy + out2 + mark_out + 10 * out3 + out4

    q = np.zeros((biorbd_model.nbQ(), markers.shape[2]))
    bounds = [(mini, maxi) for mini, maxi in zip(utils.get_range_q(biorbd_model)[0], utils.get_range_q(biorbd_model)[1])]
    for f in range(markers.shape[2]):
        x0 = q0 if f == 0 else q[:, f - 1]
        pos = optimize.minimize(
            fun=objective_function,
            args=(biorbd_model, q_ik_1[: , f], markers[:, 14:, f], markers[:, 0:14, f]),
            x0=x0,
            bounds=bounds,
            method="trust-constr",
            jac="3-point",
            tol=1e-5,
        )
        q[:, f] = pos.x
        print(f"frame {f} done")

    return q


def IK_Kinova_RT(model_path: str, q0: np.ndarray, targetd: np.ndarray, targetp: np.ndarray):
    """

    :param targetd:
    :param targetp:
    :param q0:
    :type model_path: object
    """
    m = biorbd.Model(model_path)
    bound_min = []
    bound_max = []
    for i in range(m.nbSegment()):
        seg = m.segment(i)
        for r in seg.QRanges():
            bound_min.append(r.min())
            bound_max.append(r.max())
    bounds = (bound_min, bound_max)

    def objective_function(x, *args, **kwargs):
        markers = m.markers(x)
        out1 = np.linalg.norm(markers[0].to_array() - targetd) ** 2
        out3 = np.linalg.norm(markers[-1].to_array() - targetp) ** 2
        T1 = m.globalJCS(x, m.nbSegment() - 1).to_array()
        out2 = T1[2, 0] ** 2 + T1[2, 1] ** 2 + T1[0, 2] ** 2 + T1[1, 2] ** 2 + (1 - T1[2, 2]) ** 2
        T2 = m.globalJCS(x, 0).to_array()
        out4 = np.sum((T2[:3, :3] - np.eye(3)) ** 2)
        # print(out2)
        # print(out1)
        return 10 * out1 + out2 + 10 * out3 + out4

    pos = optimize.least_squares(
        objective_function,
        args=(m, targetd, targetp),
        x0=q0,
        bounds=bounds,
        verbose=2,
        method="trf",
        jac="3-point",
        ftol=2.22e-16,
        gtol=2.22e-16,
    )
    # print(pos)
    # print(f"Optimal q for the assistive arm at {target} is:\n{pos.x}\n"
    #       f"with cost function = {objective_function(pos.x)}")
    # print(m.globalJCS(q0, m.nbSegment()-1).to_array())
    # print(m.globalJCS(pos.x, m.nbSegment()-1).to_array())
    # Verification
    # q = np.tile(pos.x, (10, 1)).T
    # q = np.tile(q0, (10, 1)).T
    return pos.x