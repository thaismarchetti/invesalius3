from queue import Queue
from threading import Event
from types import SimpleNamespace

import numpy as np

from invesalius.data.coregistration import CoordinateCorregistrate


def test_coordinate_corregistration_uses_probe_without_registered_objects():
    event = Event()
    coord_queue = Queue(maxsize=1)

    class TrackerCoordinates:
        def GetCoordinates(self):
            event.set()
            return np.array([[1.0, 2.0, 3.0, 0.0, 0.0, 0.0]]), [True]

    thread = CoordinateCorregistrate(
        ref_mode_id=0,
        tracker=SimpleNamespace(TrackerCoordinates=TrackerCoordinates()),
        coreg_data=(np.eye(4), np.eye(3)),
        obj_datas={},
        view_tracts=False,
        queues=[coord_queue, Queue(), Queue(), Queue()],
        event=event,
        sle=0.001,
        tracker_id=0,
        target=None,
        icp=SimpleNamespace(use_icp=False, m_icp=None),
        e_field_loaded=False,
        navigation=SimpleNamespace(main_coil=None),
    )

    thread.run()

    coords, _, matrices = coord_queue.get_nowait()
    assert set(coords) == {"probe"}
    assert "probe" in matrices
