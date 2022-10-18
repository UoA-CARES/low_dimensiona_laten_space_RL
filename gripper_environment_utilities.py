

import cv2
from gripper_motor_utilities import Motor
from gripper_vision_utilities import VisionCamera

import numpy as np
import random


class RL_ENV:

    def __init__(self):
        self.motors_config = Motor()
        self.vision_config = VisionCamera()

        self.angle_valve_deg  = 0


    def generate_sample_act(self):
        act_m1 = np.clip(random.uniform(-1, 1), -1, 1)
        act_m2 = np.clip(random.uniform(-1, 1), -1, 1)
        act_m3 = np.clip(random.uniform(-1, 1), -1, 1)
        act_m4 = np.clip(random.uniform(-1, 1), -1, 1)
        action_vector = np.array([act_m1, act_m2, act_m3, act_m4])
        return action_vector


    def env_step(self, actions):
        id_1_dxl_goal_position = (actions[0] - (-1)) * (700 - 300) / (1 - (-1)) + 300
        id_2_dxl_goal_position = (actions[1] - (-1)) * (700 - 300) / (1 - (-1)) + 300
        id_3_dxl_goal_position = (actions[2] - (-1)) * (700 - 300) / (1 - (-1)) + 300
        id_4_dxl_goal_position = (actions[3] - (-1)) * (700 - 300) / (1 - (-1)) + 300

        id_1_dxl_goal_position = int(id_1_dxl_goal_position)
        id_2_dxl_goal_position = int(id_2_dxl_goal_position)
        id_3_dxl_goal_position = int(id_3_dxl_goal_position)
        id_4_dxl_goal_position = int(id_4_dxl_goal_position)

        self.motors_config.move_motor_step(id_1_dxl_goal_position,
                                           id_2_dxl_goal_position,
                                           id_3_dxl_goal_position,
                                           id_4_dxl_goal_position)

    def state_space_function(self):
        while True:
            self.angle_valve_deg,  detection_status = self.vision_config.get_aruco_angle()
            if detection_status:
                break
            else:
                # this means something is wrong with the detection
                pass

        return self.angle_valve_deg


    def get_sample_reduction(self):
        pass


    def render(self):
        pass
