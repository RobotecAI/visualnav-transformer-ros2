
import matplotlib.pyplot as plt
import os
from typing import Tuple, Sequence, Dict, Union, Optional, Callable
import numpy as np
import torch
import torch.nn as nn
from diffusers.schedulers.scheduling_ddpm import DDPMScheduler

import matplotlib.pyplot as plt
import yaml

# ROS
from sensor_msgs.msg import Image
from std_msgs.msg import Bool, Float32MultiArray
from visualnav_transformer.deployment.src.utils import msg_to_pil, to_numpy, transform_images, load_model
from visualnav_transformer.train.vint_train.training.train_utils import get_action
import torch
from PIL import Image as PILImage
import numpy as np
import argparse
import yaml
import time


# UTILS
from visualnav_transformer.deployment.src.topic_names import (IMAGE_TOPIC,
                        WAYPOINT_TOPIC,
                        SAMPLED_ACTIONS_TOPIC)


# CONSTANTS
MODEL_WEIGHTS_PATH = "model_weights"
ROBOT_CONFIG_PATH ="config/robot.yaml"
MODEL_CONFIG_PATH = "config/models.yaml"
with open(ROBOT_CONFIG_PATH, "r") as f:
    robot_config = yaml.safe_load(f)
MAX_V = robot_config["max_v"]
MAX_W = robot_config["max_w"]
RATE = robot_config["frame_rate"] 

# GLOBALS
context_queue = []
context_size = None  

# Load the model 
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print("Using device:", device)

def callback_obs(msg):
    obs_img = msg_to_pil(msg)
    if context_size is not None:
        if len(context_queue) < context_size + 1:
            context_queue.append(obs_img)
        else:
            context_queue.pop(0)
            context_queue.append(obs_img)


import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import Float32MultiArray

class ExplorationNode(Node):
    def __init__(self):
        super().__init__("exploration_node")
        
        self.create_subscription(
            Image,
            IMAGE_TOPIC,
            self.callback_obs,
            1
        )
        
        self.waypoint_pub = self.create_publisher(
            Float32MultiArray,
            WAYPOINT_TOPIC,
            1
        )
        
        self.sampled_actions_pub = self.create_publisher(
            Float32MultiArray,
            SAMPLED_ACTIONS_TOPIC,
            1
        )
        
        self.timer = self.create_timer(1.0 / RATE, self.timer_callback)

    def callback_obs(self, msg):
        # Your callback logic here
        pass

    def timer_callback(self):
        # Your periodic execution logic here
        pass

def main(args: argparse.Namespace):
    global context_size

    # load model parameters
    with open(MODEL_CONFIG_PATH, "r") as f:
        model_paths = yaml.safe_load(f)

    model_config_path = model_paths[args.model]["config_path"]
    with open(model_config_path, "r") as f:
        model_params = yaml.safe_load(f)

    context_size = model_params["context_size"]

    # load model weights
    ckpth_path = model_paths[args.model]["ckpt_path"]
    if os.path.exists(ckpth_path):
        print(f"Loading model from {ckpth_path}")
    else:
        raise FileNotFoundError(f"Model weights not found at {ckpth_path}")
    model = load_model(
        ckpth_path,
        model_params,
        device,
    )
    model = model.to(device)
    model.eval()

    num_diffusion_iters = model_params["num_diffusion_iters"]
    noise_scheduler = DDPMScheduler(
        num_train_timesteps=model_params["num_diffusion_iters"],
        beta_schedule='squaredcos_cap_v2',
        clip_sample=True,
        prediction_type='epsilon'
    )

    # ROS
    rclpy.init(args=args)
    node = ExplorationNode()

    while rclpy.ok():
        # EXPLORATION MODE
        waypoint_msg = Float32MultiArray()
        if (
                len(context_queue) > model_params["context_size"]
            ):

            obs_images = transform_images(context_queue, model_params["image_size"], center_crop=False)
            obs_images = obs_images.to(device)
            fake_goal = torch.randn((1, 3, *model_params["image_size"])).to(device)
            mask = torch.ones(1).long().to(device) # ignore the goal

            # infer action
            with torch.no_grad():
                # encoder vision features
                obs_cond = model('vision_encoder', obs_img=obs_images, goal_img=fake_goal, input_goal_mask=mask)
                
                # (B, obs_horizon * obs_dim)
                if len(obs_cond.shape) == 2:
                    obs_cond = obs_cond.repeat(args.num_samples, 1)
                else:
                    obs_cond = obs_cond.repeat(args.num_samples, 1, 1)
                
                # initialize action from Gaussian noise
                noisy_action = torch.randn(
                    (args.num_samples, model_params["len_traj_pred"], 2), device=device)
                naction = noisy_action

                # init scheduler
                noise_scheduler.set_timesteps(num_diffusion_iters)

                start_time = time.time()
                for k in noise_scheduler.timesteps[:]:
                    # predict noise
                    noise_pred = model(
                        'noise_pred_net',
                        sample=naction,
                        timestep=k,
                        global_cond=obs_cond
                    )

                    # inverse diffusion step (remove noise)
                    naction = noise_scheduler.step(
                        model_output=noise_pred,
                        timestep=k,
                        sample=naction
                    ).prev_sample
                print("time elapsed:", time.time() - start_time)

            naction = to_numpy(get_action(naction))
            
            sampled_actions_msg = Float32MultiArray()
            sampled_actions_msg.data = np.concatenate((np.array([0]), naction.flatten()))
            node.sampled_actions_pub.publish(sampled_actions_msg)

            naction = naction[0] # change this based on heuristic

            chosen_waypoint = naction[args.waypoint]

            if model_params["normalize"]:
                chosen_waypoint *= (MAX_V / RATE)
            waypoint_msg.data = chosen_waypoint
            node.waypoint_pub.publish(waypoint_msg)
            print("Published waypoint")
        rate.sleep()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Code to run GNM DIFFUSION EXPLORATION on the locobot")
    parser.add_argument(
        "--model",
        "-m",
        default="nomad",
        type=str,
        help="model name (hint: check ../config/models.yaml) (default: nomad)",
    )
    parser.add_argument(
        "--waypoint",
        "-w",
        default=2, # close waypoints exihibit straight line motion (the middle waypoint is a good default)
        type=int,
        help=f"""index of the waypoint used for navigation (between 0 and 4 or 
        how many waypoints your model predicts) (default: 2)""",
    )
    parser.add_argument(
        "--num-samples",
        "-n",
        default=8,
        type=int,
        help=f"Number of actions sampled from the exploration model (default: 8)",
    )
    args = parser.parse_args()
    print(f"Using {device}")
    main(args)

