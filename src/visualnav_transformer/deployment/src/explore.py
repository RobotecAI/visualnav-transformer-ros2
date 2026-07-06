import argparse
import os
import time

import numpy as np
import rclpy
import torch
import yaml
from diffusers.schedulers.scheduling_ddpm import DDPMScheduler
from rclpy.node import Node

# ROS
from sensor_msgs.msg import Image
from std_msgs.msg import Float32MultiArray

# UTILS
from visualnav_transformer.deployment.src.topic_names import (
    IMAGE_TOPIC,
    SAMPLED_ACTIONS_TOPIC,
    WAYPOINT_TOPIC,
)
from visualnav_transformer.deployment.src.utils import (
    load_model,
    msg_to_pil,
    to_numpy,
    transform_images,
)
from visualnav_transformer.train.vint_train.training.train_utils import get_action

# CONSTANTS
MODEL_WEIGHTS_PATH = "model_weights"
ROBOT_CONFIG_PATH = "config/robot.yaml"
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


class ExplorationNode(Node):
    def __init__(self):
        super().__init__("exploration_node")

        self.create_subscription(Image, IMAGE_TOPIC, callback_obs, 10)

        self.waypoint_pub = self.create_publisher(Float32MultiArray, WAYPOINT_TOPIC, 1)

        self.sampled_actions_pub = self.create_publisher(
            Float32MultiArray, SAMPLED_ACTIONS_TOPIC, 1
        )


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
        beta_schedule="squaredcos_cap_v2",
        clip_sample=True,
        prediction_type="epsilon",
    )

    # ROS
    rclpy.init()
    node = ExplorationNode()

    while rclpy.ok():
        loop_start_time = time.time()
        # EXPLORATION MODE
        waypoint_msg = Float32MultiArray()
        if len(context_queue) > model_params["context_size"]:
            obs_images = transform_images(
                context_queue, model_params["image_size"], center_crop=False
            )
            obs_images = obs_images.to(device)
            fake_goal = torch.randn((1, 3, *model_params["image_size"])).to(device)
            mask = torch.ones(1).long().to(device)  # ignore the goal

            # infer action
            with torch.no_grad():
                # encoder vision features
                obs_cond = model(
                    "vision_encoder",
                    obs_img=obs_images,
                    goal_img=fake_goal,
                    input_goal_mask=mask,
                )

                # (B, obs_horizon * obs_dim)
                if len(obs_cond.shape) == 2:
                    obs_cond = obs_cond.repeat(args.num_samples, 1)
                else:
                    obs_cond = obs_cond.repeat(args.num_samples, 1, 1)

                # initialize action from Gaussian noise
                noisy_action = torch.randn(
                    (args.num_samples, model_params["len_traj_pred"], 2), device=device
                )
                naction = noisy_action

                # init scheduler
                noise_scheduler.set_timesteps(num_diffusion_iters)

                start_time = time.time()
                for k in noise_scheduler.timesteps[:]:
                    # predict noise
                    noise_pred = model(
                        "noise_pred_net",
                        sample=naction,
                        timestep=k,
                        global_cond=obs_cond,
                    )

                    # inverse diffusion step (remove noise)
                    naction = noise_scheduler.step(
                        model_output=noise_pred, timestep=k, sample=naction
                    ).prev_sample
                inference_time = time.time() - start_time

            naction = to_numpy(get_action(naction))
            sampled_actions_msg = Float32MultiArray()
            sampled_actions_msg.data = np.concatenate(
                (np.array([0]), naction.flatten())
            ).tolist()
            node.sampled_actions_pub.publish(sampled_actions_msg)

            naction = naction[0]  # change this based on heuristic

            chosen_waypoint = naction[args.waypoint]

            if model_params["normalize"]:
                chosen_waypoint *= MAX_V / RATE
            waypoint_msg.data = chosen_waypoint.tolist()
            node.waypoint_pub.publish(waypoint_msg)

            node.get_logger().info(
                f"Published waypoint {np.round(chosen_waypoint, 2).tolist()} "
                f"(inference: {inference_time:.2f}s)",
                throttle_duration_sec=1.0,
            )
            elapsed_time = time.time() - loop_start_time
            sleep_time = max(0, (1.0 / RATE) - elapsed_time)
            time.sleep(sleep_time)
        rclpy.spin_once(node, timeout_sec=0)

    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Code to run GNM DIFFUSION EXPLORATION on the locobot"
    )
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
        default=2,  # close waypoints exihibit straight line motion (the middle waypoint is a good default)
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
