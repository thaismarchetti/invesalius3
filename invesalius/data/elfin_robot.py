import numpy as np
import cv2
from time import time, sleep
import queue
import threading
import csv

import invesalius.data.elfin as elfin
import invesalius.data.transformations as tr


class elfin_server():
    def __init__(self, server_ip='169.254.153.251', port_number=10003):
        self.server_ip = server_ip
        self.port_number = port_number
        #print(cobot.ReadPcsActualPos())

    def Initialize(self):
        SIZE = 1024
        rbtID = 0
        self.cobot = elfin.elfin()
        self.cobot.connect(self.server_ip, self.port_number, SIZE, rbtID)
        print("conected!")

    def Run(self):
        #target = [540.0, -30.0, 850.0, 140.0, -81.0, -150.0]
        #print("starting move")
        return self.cobot.ReadPcsActualPos()

    def SendCoordinates(self, target):
        status = self.cobot.ReadMoveState()
        if status != 1009:
            self.cobot.MoveL(target)

    def Close(self):
        self.cobot.close()

class KalmanTracker:

    def __init__(self,
                 state_num=2,
                 cov_process=0.001,
                 cov_measure=0.1):

        self.state_num = state_num
        measure_num = 1

        # The filter itself.
        self.filter = cv2.KalmanFilter(state_num, measure_num, 0)

        self.state = np.zeros((state_num, 1), dtype=np.float32)
        self.measurement = np.array((measure_num, 1), np.float32)
        self.prediction = np.zeros((state_num, 1), np.float32)


        self.filter.transitionMatrix = np.array([[1, 1],
                                                 [0, 1]], np.float32)
        self.filter.measurementMatrix = np.array([[1, 1]], np.float32)
        self.filter.processNoiseCov = np.array([[1, 0],
                                                [0, 1]], np.float32) * cov_process
        self.filter.measurementNoiseCov = np.array( [[1]], np.float32) * cov_measure

    def update_kalman(self, measurement):
        self.prediction = self.filter.predict()
        self.measurement = np.array([[np.float32(measurement[0])]])

        self.filter.correct(self.measurement)
        self.state = self.filter.statePost

class TrackerProcessing:
    def __init__(self):
        self.coord_vel = []
        self.timestamp = []
        self.velocity_vector = []
        self.kalman_coord_vector = []
        self.velocity_std = 0

        self.tracker_stabilizers = [KalmanTracker(
            state_num=2,
            cov_process=0.001,
            cov_measure=0.1) for _ in range(6)]


    def kalman_filter(self, coord_tracker):
        kalman_array = []
        pose_np = np.array((coord_tracker[:3], coord_tracker[3:])).flatten()
        for value, ps_stb in zip(pose_np, self.tracker_stabilizers):
            ps_stb.update_kalman([value])
            kalman_array.append(ps_stb.state[0])
        coord_kalman = np.hstack(kalman_array)

        self.kalman_coord_vector.append(coord_kalman[:3])
        if len(self.kalman_coord_vector) < 20: #avoid initial fluctuations
            coord_kalman = coord_tracker
            print('initializing filter')
        else:
            del self.kalman_coord_vector[0]

        return coord_kalman


    def estimate_head_velocity(self, coord_vel, timestamp):
        coord_vel = np.vstack(np.array(coord_vel))
        coord_init = coord_vel[:int(len(coord_vel)/2)].mean(axis=0)
        coord_final = coord_vel[int(len(coord_vel)/2):].mean(axis=0)
        velocity = (coord_final - coord_init)/(timestamp[-1]-timestamp[0])
        distance = (coord_final - coord_init)

        return velocity, distance


    def head_move_threshold(self, current_ref):
        self.coord_vel.append(current_ref)
        self.timestamp.append(time())
        if len(self.coord_vel) >= 10:
            head_velocity, head_distance = self.estimate_head_velocity(self.coord_vel, self.timestamp)
            self.velocity_vector.append(head_velocity)

            del self.coord_vel[0]
            del self.timestamp[0]

            if len(self.velocity_vector) >= 30:
                self.velocity_std = np.std(self.velocity_vector)
                del self.velocity_vector[0]

            if self.velocity_std > 5:
                print('Velocity threshold activated')
                return False
            else:
                return True

        return False


    def head_move_compensation(self, current_ref, m_change_robot2ref):
        trans = tr.translation_matrix(current_ref[:3])
        a, b, g = np.radians(current_ref[3:6])
        rot = tr.euler_matrix(a, b, g, 'rzyx')
        M_current_ref = tr.concatenate_matrices(trans, rot)

        m_robot_new = M_current_ref @ m_change_robot2ref
        _, _, angles, translate, _ = tr.decompose_matrix(m_robot_new)
        angles = np.degrees(angles)

        return m_robot_new[0, -1], m_robot_new[1, -1], m_robot_new[2, -1], angles[0], angles[1], \
                    angles[2]


    def transform_tracker_2_robot(self, coord_tracker):
        M_robot_2_tracker = [[3.41541979e-01, 9.39589953e-01, 2.27990560e-02, -3.39484527e+02],
                             [8.40244849e-02, -6.36439415e-03, -9.96443365e-01, 2.28264256e+02],
                             [-9.36103073e-01, 3.42242918e-01, -8.11222696e-02, 1.65836850e+03],
                             [0.00000000e+00, 0.00000000e+00, 0.00000000e+00, 1.00000000e+00]]

        M_tracker_2_robot = tr.inverse_matrix(M_robot_2_tracker)

        trans = tr.translation_matrix(coord_tracker[:3])
        a, b, g = np.radians(coord_tracker[3:6])
        rot = tr.euler_matrix(a, b, g, 'rzyx')
        M_tracker = tr.concatenate_matrices(trans, rot)
        M_tracker_in_robot = M_tracker_2_robot @ M_tracker

        _, _, angles, translate, _ = tr.decompose_matrix(M_tracker_in_robot)
        tracker_in_robot = [translate[0], translate[1], translate[2], \
                            np.degrees(angles[2]), np.degrees(angles[1]), np.degrees(angles[0])]

        return tracker_in_robot

def ClaronCoord(trck_init):
    trck = trck_init[0]
    trck.Run()
    scale = np.array([1.0, 1.0, 1.0])

    coord1 = np.array([float(trck.PositionTooltipX1)*scale[0], float(trck.PositionTooltipY1)*scale[1],
                      float(trck.PositionTooltipZ1)*scale[2],
                      float(trck.AngleZ1), float(trck.AngleY1), float(trck.AngleX1)])

    coord2 = np.array([float(trck.PositionTooltipX2)*scale[0], float(trck.PositionTooltipY2)*scale[1],
                       float(trck.PositionTooltipZ2)*scale[2],
                       float(trck.AngleZ2), float(trck.AngleY2), float(trck.AngleX2)])

    coord3 = np.array([float(trck.PositionTooltipX3) * scale[0], float(trck.PositionTooltipY3) * scale[1],
                       float(trck.PositionTooltipZ3) * scale[2],
                       float(trck.AngleZ3), float(trck.AngleY3), float(trck.AngleX3)])

    coord = np.vstack([coord1, coord2, coord3])

    return coord

class ControlRobot(threading.Thread):
    def __init__(self, trck_init, queues, process_tracker, event):
        threading.Thread.__init__(self, name='ControlRobot')


        self.trck_init_robot = trck_init[1][0]
        self.trck_init_tracker = trck_init[0]
        self.robot_tracker_flag = False
        self.m_change_robot2ref = None
        self.robot_coord_queue = queues[0]
        self.coord_queue = queues[1]
        self.robottarget_queue = queues[2]
        self.process_tracker = process_tracker
        self.event = event
        self.time_start = time()
        self.fieldnames = ['time', 'x','xf','statusx']
        with open('data.csv', 'w') as csv_file:
            csv_writer = csv.DictWriter(csv_file, fieldnames=self.fieldnames)
            csv_writer.writeheader()


    def run(self):

        while not self.event.is_set():
            start = time()
            probe = self.trck_init_robot.Run()
            probe[3], probe[5] = probe[5], probe[3]
            coord_robot = np.array(probe)
            try:
                self.robot_coord_queue.put_nowait(coord_robot)
            except queue.Full or queue.Empty:
                pass

            #coord_raw, markers_flag = dco.GetCoordinates(self.trck_init_tracker, const.MTC, const.DEFAULT_REF_MODE)
            coord_raw = ClaronCoord(self.trck_init_tracker)
            coord_tracker_in_robot = self.process_tracker.transform_tracker_2_robot(coord_raw[1])


            if self.robottarget_queue.empty():
                None
            else:
                self.robot_tracker_flag, self.m_change_robot2ref = self.robottarget_queue.get_nowait()
            current_ref_filtered = [0]
            if self.robot_tracker_flag:
                current_ref = coord_tracker_in_robot
                if current_ref is not None:
                    current_ref_filtered = self.process_tracker.kalman_filter(current_ref)
                    if self.process_tracker.head_move_threshold(current_ref_filtered):
                        coord_inv = self.process_tracker.head_move_compensation(current_ref_filtered, self.m_change_robot2ref)
                        self.trck_init_robot.SendCoordinates(coord_inv)
                        #print('send')

            if not self.robottarget_queue.empty():
                self.robottarget_queue.task_done()

            with open('data.csv', 'a') as csv_file:
                csv_writer = csv.DictWriter(csv_file, fieldnames=self.fieldnames)

                info = {
                    "time": time() - self.time_start,
                    "x": coord_tracker_in_robot[0],
                    "xf": current_ref_filtered[0],
                    "statusx": self.process_tracker.velocity_std,
                }

                csv_writer.writerow(info)

            end = time()
            #print("                   ", end - start)
        #print('hi')