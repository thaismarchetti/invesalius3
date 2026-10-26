from types import SimpleNamespace

from invesalius.navigation.navigation import UpdateNavigationScene


def test_probe_pose_update_includes_marker_visibility(mocker):
    send_message = mocker.patch(
        "invesalius.navigation.navigation.Publisher.sendMessage"
    )
    scene = object.__new__(UpdateNavigationScene)
    scene._dispatch_pending = True
    scene.peel_loaded = False
    scene.e_field_loaded = False
    probe_matrix = SimpleNamespace()

    scene._dispatch_updates(
        update_pose=True,
        render=False,
        slice_render=False,
        coord=[1.0, 2.0, 3.0],
        probe_visible=True,
        head_visible=False,
        probe_coord=[1.0, 2.0, 3.0],
        probe_m_img=probe_matrix,
        coil_visible=False,
        main_coil=None,
        coords={},
        m_imgs={},
        tracts_payload=None,
        trigger_on=False,
        enorm_data=None,
    )

    send_message.assert_any_call(
        "Update probe pose",
        m_img=probe_matrix,
        coord=[1.0, 2.0, 3.0],
        probe_visible=True,
        head_visible=False,
    )
    assert scene._dispatch_pending is False
