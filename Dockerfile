# ROS distro to build for: jazzy (Ubuntu 24.04) or humble (Ubuntu 22.04)
ARG ROS_DISTRO=jazzy
FROM osrf/ros:${ROS_DISTRO}-desktop
ARG ROS_DISTRO

# Avoid prompts from apt
ENV DEBIAN_FRONTEND=noninteractive

# Ubuntu 24.04 (jazzy) pip refuses system-wide installs without this
ENV PIP_BREAK_SYSTEM_PACKAGES=1

# Disable shared memory for FastRTPS
RUN echo "<?xml version=\"1.0\" encoding=\"UTF-8\" ?> \
<profiles xmlns=\"http://www.eprosima.com/XMLSchemas/fastRTPS_Profiles\" > \
    <transport_descriptors> \
        <transport_descriptor> \
            <transport_id>CustomUdpTransport</transport_id> \
            <type>UDPv4</type> \
        </transport_descriptor> \
    </transport_descriptors> \
    <participant profile_name=\"participant_profile\" is_default_profile=\"true\"> \
        <rtps> \
            <userTransports> \
                <transport_id>CustomUdpTransport</transport_id> \
            </userTransports> \
            <useBuiltinTransports>false</useBuiltinTransports> \
        </rtps> \
    </participant> \
</profiles>" > /fastrtps_disable_shm.xml
ENV FASTRTPS_DEFAULT_PROFILES_FILE=/fastrtps_disable_shm.xml

# Install git and python3-pip
RUN apt-get update && apt-get install -y \
    git \
    python3-pip \
    python3-colcon-common-extensions \
    python3-argcomplete \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
RUN pip3 install gdown

# Install uv
RUN pip3 install uv

# Clone the VisualNav-Transformer repository
RUN git clone https://github.com/Robotecai/visualnav-transformer-ros2.git /visualnav-transformer

# Set up environment variables
RUN echo "source /opt/ros/${ROS_DISTRO}/setup.bash" >> ~/.bashrc

# Set the working directory
WORKDIR /visualnav-transformer

# Install dependencies using uv
RUN uv sync

RUN mkdir /visualnav-transformer/model_weights
RUN gdown https://drive.google.com/uc?id=1YJhkkMJAYOiKNyCaelbS_alpUpAJsOUb -O /visualnav-transformer/model_weights/nomad.pth

# Set the entrypoint
ENTRYPOINT ["/bin/bash"]
