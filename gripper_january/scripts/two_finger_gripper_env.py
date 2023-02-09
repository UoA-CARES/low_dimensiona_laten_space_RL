
import logging
import numpy as np

from Camera import Camera
from gripper_configuration import Gripper, GripperError

#from cares_lib.vision.ArucoDetector import ArucoDetector
from gripper_aruco_detector import ArucoDetector  # TODO use the lib from cares

#logging.basicConfig(level=logging.DEBUG)

class GripperEnvironment:
    def __init__(self):
        self.num_motors = 4
        self.gripper    = Gripper(num_motors=self.num_motors)
        self.camera     = Camera()

        self.aruco_detector = ArucoDetector(marker_size=18) # todo use the lib from cares
        self.target_angle   = self.choose_target_angle()

        self.object_marker_id  = 6
        self.marker_ids_vector = [0, 1, 2, 3, 4, 5, 6]

    def reset(self):
        try:
            current_servo_positions = self.gripper.home()
        except GripperError as error:
            # handle what to do if the gripper is unrecoverably gone wrong - i.e. save data and fail gracefully
            logging.error(error)
            exit()

        marker_pose_all        = self.find_marker_pose(marker_ids_vector=self.marker_ids_vector)
        object_marker_yaw      = marker_pose_all[self.object_marker_id][1][2]
        marker_coordinates_all = self.find_joint_coordinates(marker_pose_all)

        state = self.define_state_space(current_servo_positions, marker_coordinates_all, object_marker_yaw)
        self.target_angle = self.choose_target_angle()
        return state


    def choose_target_angle(self):
        target_angle = np.random.randint(1, 5)
        if target_angle == 1:
            return 90
        elif target_angle == 2:
            return 180
        elif target_angle == 3:
            return 270
        elif target_angle == 4:
            return 0


    def reward_function(self, target_angle, start_marker_pose, final_marker_pose):
        done = False
        valve_angle_before = start_marker_pose
        valve_angle_after  = final_marker_pose

        angle_difference = np.abs(target_angle - valve_angle_after)
        delta_changes    = np.abs(target_angle - valve_angle_before) - np.abs(target_angle - valve_angle_after)

        noise_tolerance = 3
        if -noise_tolerance <= delta_changes <= noise_tolerance:
            reward = 0
        else:
            reward = delta_changes

        if angle_difference <= noise_tolerance:
            reward = reward + 100
            logging.debug("Reached the Goal Angle!")
            done = True

        return reward, done

    def find_marker_pose(self, marker_ids_vector):
        i = 0
        while True:
            i += 1
            logging.debug(f"Attempting to detect markers attempt {i}")
            frame = self.camera.get_frame()
            marker_poses = self.aruco_detector.get_marker_poses(frame, self.camera.camera_matrix, self.camera.camera_distortion)
            # this check if all the seven marker are detected and return all the poses
            if all(ids in marker_poses for ids in marker_ids_vector):
                break
        return marker_poses

    def find_joint_coordinates(self, markers_pose):
        # the ids detected may have a different order of detection
        # i.e. sometimes the markers_pose index maybe [0, 2, 3] and other [0, 3, 2]
        # so getting x and y coordinates in the right order
        markers_xy_coordinates = []
        for id_index, id_detected in enumerate(markers_pose):
            markers_xy_coordinates.append(markers_pose[id_index][0][0][:-1])
        return markers_xy_coordinates

    def define_state_space(self, servos_position, marker_coordinates, object_marker_yaw):
        #todo include Goal angle in the state_space_vector
        state_space_vector = []
        mode = 3
        if mode == 1:
            servos_position.append(object_marker_yaw)
            state_space_vector = servos_position
        elif mode == 2:
            coordinate_vector = [element for state_space_list in marker_coordinates for element in state_space_list]
            coordinate_vector.append(object_marker_yaw)
            for i in servos_position:
                coordinate_vector.append(i)
            state_space_vector = coordinate_vector
        elif mode == 3:
            coordinate_vector = [element for state_space_list in marker_coordinates for element in state_space_list]
            coordinate_vector.append(object_marker_yaw)
            state_space_vector = coordinate_vector
        return state_space_vector

    def step(self, action):
        start_marker_pose_all        = self.find_marker_pose(marker_ids_vector=self.marker_ids_vector)
        start_object_marker_yaw      = start_marker_pose_all[self.object_marker_id][1][2]
        start_marker_coordinates_all = self.find_joint_coordinates(start_marker_pose_all)

        try:
            action = self.gripper.action_to_steps(action)
            current_servo_positions = self.gripper.move(steps=action)
        except GripperError as error:
            # handle what to do if the gripper is unrecoverably gone wrong - i.e. save data and fail gracefully
            logging.error(error)
            exit()

        final_marker_pose_all        = self.find_marker_pose(marker_ids_vector=self.marker_ids_vector)
        final_object_marker_yaw      = final_marker_pose_all[self.object_marker_id][1][2]
        final_marker_coordinates_all = self.find_joint_coordinates(final_marker_pose_all)

        state        = self.define_state_space(current_servo_positions, final_marker_coordinates_all, final_object_marker_yaw)
        reward, done = self.reward_function(self.target_angle, start_object_marker_yaw, final_object_marker_yaw)
        truncated    = False  # never truncate the episode but here for completion sake

        return state, reward, done, truncated
