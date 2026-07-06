# General Navigation Models: GNM, ViNT and NoMaD

This repository is a port of [visualnav-transformer](https://github.com/robodhruv/visualnav-transformer) to ROS2. Its purpose is to make running the models more straightforward by providing a Dockerfile with all dependencies set up. For more details on the models, please refer to the original repository.

### Installation (uv)

The project's Python dependencies are managed with [uv](https://docs.astral.sh/uv/). The Docker images below install everything automatically, but for a local (non-Docker) setup:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv -p 3.12   # ROS2 Jazzy; use -p 3.10 for Humble
uv sync
```

The Python version must match your ROS distro: 3.12 for Jazzy, 3.10 for Humble. Requires a ROS2 installation sourced in your shell.

### Running the code

1. Clone the repository:
```bash
git clone https://github.com/RobotecAI/visualnav-transformer-ros2
cd visualnav-transformer-ros2
```

2. Build the Docker image:

The image is based on the [`osrf/ros`](https://hub.docker.com/r/osrf/ros) desktop images and can be built for ROS2 Jazzy (default) or Humble via the `ROS_DISTRO` build argument:
```bash
# ROS2 Jazzy (Ubuntu 24.04)
docker build -t visualnav_transformer:latest .

# ROS2 Humble (Ubuntu 22.04)
docker build --build-arg ROS_DISTRO=humble -t visualnav_transformer:latest .
```

3. Run the Docker container:

**NVIDIA GPU** (requires the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)):
```bash
docker run -it --env ROS_DOMAIN_ID=$ROS_DOMAIN_ID --rm --gpus=all --net=host visualnav_transformer:latest
```

**AMD GPU** (requires [ROCm](https://rocm.docs.amd.com/) drivers on the host):
```bash
docker run -it --env ROS_DOMAIN_ID=$ROS_DOMAIN_ID --rm --net=host \
    --device=/dev/kfd --device=/dev/dri \
    --group-add video --security-opt seccomp=unconfined \
    visualnav_transformer:latest
```

The image ships with the default (CUDA) PyTorch build. On AMD, replace it with the ROCm build inside the container:
```bash
uv pip install torch==2.3.1 --index-url https://download.pytorch.org/whl/rocm7.2
```

4. Run the model:

Inside the container, run the following commands:
```bash
uv run python src/visualnav_transformer/deployment/src/explore.py
```

> Tip: instead of prefixing every command with `uv run`, you can activate the environment once with `source .venv/bin/activate` and call `python` directly.

This will run the model and publish the predicted waypoints to a ROS2 topic, but your robot will not move yet. Next to running the model you have to run a script that will publish the movement commands to the robot.

```bash
uv run python scripts/publish_cmd.py
```

Now the robot should start moving based on the model's predictions.

To visualize the waypoints that the model is outputting you can run the following command:
```bash
uv run python scripts/visualize.py
```
A window should appear with the camera image and the model outputs updated in real time.

### Creating a topomap of the environment

In order to navigate to a desired goal location, the robot needs to have a map of the environment. To create a topomap of the environment, you can run the following command:
```bash
uv run python src/visualnav_transformer/deployment/src/create_topomap.py
```
The script will save an image from the camera every second (this interval can be changed with the `-t` parameter). Now you can drive the robot around the environment manually (using your navigation stack or teleop) and the map will be saved automatically. After you have driven around the environment, you can stop the script and proceed to the next step.

### Navigation
Having created a topomap of the environment, you can now run the navigation script:
```bash
uv run python src/visualnav_transformer/deployment/src/navigate.py
```
By default the robot will try to follow the topomap to reach the last image captured. You can specify a different goal image by providing an index of an image in the topomap using the `--goal-node` parameter.
